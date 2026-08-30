import logging
import os
from typing import List, Optional
from datetime import datetime

from domain.models import CollectionRunResult, StockSplitDisclosure, StockSplitDisclosureChain
from ports.scraper import StockSplitScraperPort
from ports.parser import StockSplitParserPort
from ports.repository import StockSplitReaderPort, StockSplitWriterPort, CloudSyncPort

logger = logging.getLogger(__name__)

class StockSplitCollectionService:
    """
    주식분할결정 공시 수집 및 로컬-원격 스마트 동기화 유스케이스를 관장하는 애플리케이션 서비스
    
    헥사고날 아키텍처의 원칙에 따라 구체 기술(어댑터)에 의존하지 않고, 
    생성자 주입(DI)을 통해 포트 인터페이스들만 결합하여 비즈니스 흐름을 제어합니다.
    """

    def __init__(
        self,
        scraper_port: StockSplitScraperPort,
        parser_port: StockSplitParserPort,
        reader_port: StockSplitReaderPort,
        writer_port: StockSplitWriterPort,
        sync_port: Optional[CloudSyncPort] = None
    ) -> None:
        self.scraper_port = scraper_port
        self.parser_port = parser_port
        self.reader_port = reader_port
        self.writer_port = writer_port
        self.sync_port = sync_port

    def collect_splits_for_period(
        self,
        start_date: str,
        end_date: str,
        keyword: str = "주식분할결정",
        exclude_corrections: bool = True,
        force_refresh: bool = False
    ) -> CollectionRunResult:
        """
        특정 기간 동안의 주식분할결정 공시들을 전체 수집, 본문 파싱, 데이터 검증 후
        영속화 저장소 및 클라우드 드라이브 동기화까지 통합 비즈니스 흐름을 오케스트레이션합니다.
        이미 DB에 저장된 접수번호는 force_refresh가 아닌 한 재파싱하지 않습니다.
        """
        logger.info(f"[Service] Pipeline started for period: {start_date} ~ {end_date}")
        current_year = datetime.now().year

        # 1. 아웃바운드 포트를 사용하여 시작 전 구글 드라이브에서 SSOT DB 파일 스마트 대조 다운로드
        if self.sync_port and not force_refresh:
            logger.info("[Service] Smart sync checking on Google Drive (SSOT)...")
            try:
                self.sync_port.sync_down_if_newer(
                    remote_name="stock_splits.db",
                    local_path="data/stock_splits.db"
                )
                logger.info("[Service] Smart sync download check completed.")
            except Exception as se:
                logger.warning(f"[Service] Smart sync download failed (Continuing with local): {se}")

        # 2. 기존 데이터베이스 로드 (완료 판정 및 증분 수집/머지 지원)
        existing_disclosures: List[StockSplitDisclosure] = []
        try:
            existing_disclosures = self.reader_port.load_all()
        except Exception as e:
            logger.warning(f"[Service] Failed to load existing disclosures: {e}")
        existing_map = {d.rcept_no: d for d in existing_disclosures}

        # 3. 아웃바운드 포트를 사용하여 공시 목록 메타데이터 수집
        disclosures_meta = self.scraper_port.fetch_disclosures(
            start_date=start_date,
            end_date=end_date,
            keyword=keyword,
            exclude_corrections=exclude_corrections
        )

        if not disclosures_meta:
            logger.info("[Service] No disclosures found for the specified period.")
            return CollectionRunResult(disclosures=existing_disclosures)

        # 중복 방지 및 복원 적재를 위한 접수번호 기준 맵 구성
        meta_map = {m["rcept_no"]: m for m in disclosures_meta}
        relation_map = {}

        logger.info("[Service] Analyzing corrections and fetching history disclosures...")
        
        # 기재정정 공시들에 대해 이전 히스토리 공시들을 자동으로 추적하여 복원 적재
        meta_list = list(disclosures_meta)
        for meta in meta_list:
            report_nm = meta.get("report_nm", "")
            curr_rcp = meta.get("rcept_no")
            
            if not curr_rcp:
                continue

            # 정정 공시 혹은 철회 공시 감지 시 히스토리 이력 역추적
            if "정정" in report_nm or "철회" in report_nm:
                history_ids = self.scraper_port.get_history_rcp_list(curr_rcp)
                
                # 인접한 세대별 부모-자식 공시쌍 관계 매핑 수립
                for i in range(1, len(history_ids)):
                    parent = history_ids[i-1]
                    child = history_ids[i]
                    relation_map[child] = parent

                # 누락된 이전 공시(최초 공시 등)를 메타데이터 목록에 복원 적재
                for hist_rcp in history_ids:
                    if hist_rcp not in meta_map:
                        p_reg_date = f"{hist_rcp[:4]}.{hist_rcp[4:6]}.{hist_rcp[6:8]}"
                        p_report_nm = "주식분할결정"
                        if hist_rcp == history_ids[0]:
                            p_report_nm = "[최초]주식분할결정"
                            
                        restored_meta = {
                            "corp_name": meta["corp_name"],
                            "report_nm": p_report_nm,
                            "rcept_no": hist_rcp,
                            "presenter": meta["presenter"],
                            "reg_date": p_reg_date
                        }
                        meta_map[hist_rcp] = restored_meta
                        logger.info(f"  [Service] Restored missing parent disclosure: {meta['corp_name']} ({hist_rcp}) - Date: {p_reg_date}")

        # 전체 복원 완료된 공시 목록
        final_meta_list = list(meta_map.values())
        logger.info(f"[Service] Final disclosures to process (including restored): {len(final_meta_list)}")

        # 4. 개별 공시 상세 내용 파싱 및 도메인 모델 생성
        #    이미 완료 저장된 접수번호는(§3 완료 판정: DB 조회) force_refresh가 아니면
        #    파싱 자체를 건너뛰고 기존 저장분을 그대로 재사용한다.
        final_disclosures: List[StockSplitDisclosure] = []
        skipped_existing = 0
        parsed_count = 0
        failed_rcept_nos: List[str] = []

        for i, meta in enumerate(final_meta_list, 1):
            corp_name = meta["corp_name"]
            rcept_no = meta["rcept_no"]
            reg_date = meta["reg_date"]

            if not force_refresh and rcept_no in existing_map:
                # 기존 저장분을 final_disclosures에 넣지 않는다 - 이 리스트는 아래에서
                # StockSplitDisclosureChain.resolve_original_dates()에 그대로 넘어가는데,
                # 이번 실행의 relation_map에 이 rcept_no가 없으면(정정 이력 스크래핑이 이번엔
                # 실패했거나 대상이 아닌 경우) original_reg_date가 자기 자신 날짜로 덮어써져
                # 예전에 올바르게 계산해둔 정정 체인 정보가 손상된다. 기존 저장분은 병합 단계에서
                # existing_disclosures를 통해 그대로 보존되므로 재처리할 필요가 없다.
                logger.info(f"[Service] [{i}/{len(final_meta_list)}] Already stored, skipping parse: {corp_name} ({rcept_no})")
                skipped_existing += 1
                continue

            logger.info(f"[Service] [{i}/{len(final_meta_list)}] Parsing detail for {corp_name} ({rcept_no})...")

            # 아웃바운드 포트를 사용하여 공시 XML 본문 분석
            try:
                detail = self.parser_port.parse_split_info(rcept_no, force_refresh=force_refresh)
            except Exception as pe:
                logger.warning(f"[Service] Parse failed (skipped): {pe}")
                failed_rcept_nos.append(rcept_no)
                continue

            # 공시명 자체에 '철회'가 포함되어 있거나, 공시 상세 파싱 결과에서 철회로 판별된 경우
            is_cancelled = "철회" in meta["report_nm"] or detail.get("is_cancelled", False)

            # 도메인 모델로 통합 및 유효성 검증
            try:
                disclosure_obj = StockSplitDisclosure(
                    corp_name=corp_name,
                    report_nm=meta["report_nm"],
                    rcept_no=rcept_no,
                    presenter=meta["presenter"],
                    reg_date=reg_date,
                    is_cancelled=is_cancelled,
                    parent_rcept_no=None,
                    original_reg_date=None,
                    pre_split_common_shares=detail["pre_split_common_shares"],
                    post_split_common_shares=detail["post_split_common_shares"],
                    new_share_listing_date=detail["new_share_listing_date"],
                    board_resolution_date=detail["board_resolution_date"]
                )
                final_disclosures.append(disclosure_obj)
                parsed_count += 1
            except Exception as ve:
                logger.warning(f"[Service] Validation error (skipped): {ve}")
                failed_rcept_nos.append(rcept_no)
                continue

        # 4. 정정공시 간의 최초 원본 공시일 계산 및 부모-자식 관계 맵핑 설정 (도메인 Aggregate 위임)
        if final_disclosures:
            logger.info("[Service] Resolving original dates using domain Aggregate...")
            chain = StockSplitDisclosureChain(disclosures=final_disclosures, relation_map=relation_map)
            chain.resolve_original_dates()

        # 6. 기존 데이터와 신규 수집 데이터 병합 (접수번호 기준 중복 배제)
        disclosure_map = {d.rcept_no: d for d in existing_disclosures}
        for d in final_disclosures:
            disclosure_map[d.rcept_no] = d  # 신규 데이터로 덮어쓰기 (UPSERT)
            
        merged_disclosures = list(disclosure_map.values())
        
        # 7. 전체 병합 데이터 정렬 (공시 등록일 내림차순, 동일할 시 회사명 내림차순)
        merged_disclosures.sort(key=lambda x: (x.reg_date or "", x.corp_name or ""), reverse=True)

        # 8. 아웃바운드 포트를 사용하여 복합 영속화 실행
        sync_up_failed = False
        if merged_disclosures:
            logger.info(f"[Service] Saving {len(merged_disclosures)} merged disclosures (Existing: {len(existing_disclosures)}, Parsed: {parsed_count}, Skipped: {skipped_existing})...")
            self.writer_port.save_all(merged_disclosures)

            # 9. 아웃바운드 포트를 사용하여 구글 드라이브 클라우드 동기화 업로드 기동
            if self.sync_port:
                logger.info("[Service] Commencing smart sync upload to Google Drive...")
                # 사람이 바로 확인 가능한 산출물(엑셀) 먼저, DB는 나중 (db_ssot_guide.md §3) -
                # 산출물 업로드가 실패해도 최소한 사람이 볼 결과는 최신인 상태를 우선시.
                sync_targets = [
                    (f"data/액면분할({current_year}년).xlsx", f"액면분할({current_year}년).xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    (f"data/액면분할({current_year - 1}년).xlsx", f"액면분할({current_year - 1}년).xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    (f"data/액면분할({current_year - 2}년).xlsx", f"액면분할({current_year - 2}년).xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    ("data/stock_splits.db", "stock_splits.db", "application/x-sqlite3"),
                ]

                # 각 파일 업로드를 독립적으로 시도한다 - 하나가 실패해도(sync_up_file이
                # 예외를 던짐) 나머지 파일 업로드를 계속 시도해야 한다. 예전엔 for 루프
                # 전체를 하나의 try로 묶어서, 첫 파일(DB) 실패가 나머지 엑셀 업로드
                # 시도 자체를 막았다.
                for local_path, remote_name, mime_type in sync_targets:
                    if not os.path.exists(local_path):
                        continue
                    try:
                        self.sync_port.sync_up_file(
                            local_path=local_path,
                            remote_name=remote_name,
                            mime_type=mime_type
                        )
                    except Exception as sync_err:
                        logger.error(f"[Service] Cloud sync failed for '{remote_name}': {sync_err}")
                        sync_up_failed = True

                if sync_up_failed:
                    logger.error("[Service] Google Drive cloud sync completed with failures.")
                else:
                    logger.info("[Service] Google Drive cloud sync completely succeeded!")

            logger.info("[Service] Pipeline successfully completed!")
        else:
            logger.info("[Service] No disclosures to save.")

        return CollectionRunResult(
            disclosures=merged_disclosures,
            discovered=len(final_meta_list),
            skipped_existing=skipped_existing,
            parsed=parsed_count,
            failed_rcept_nos=failed_rcept_nos,
            sync_up_failed=sync_up_failed,
        )


import os
from typing import List, Optional
from datetime import datetime

from domain.models import StockSplitDisclosure, StockSplitDisclosureChain
from ports.scraper import StockSplitScraperPort
from ports.parser import StockSplitParserPort
from ports.repository import StockSplitReaderPort, StockSplitWriterPort, CloudSyncPort

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
    ) -> List[StockSplitDisclosure]:
        """
        특정 기간 동안의 주식분할결정 공시들을 전체 수집, 본문 파싱, 데이터 검증 후 
        영속화 저장소 및 클라우드 드라이브 동기화까지 통합 비즈니스 흐름을 오케스트레이션합니다.
        """
        print(f"[Service] Pipeline started for period: {start_date} ~ {end_date}")
        current_year = datetime.now().year

        # 1. 아웃바운드 포트를 사용하여 시작 전 구글 드라이브 스마트 대조 다운로드 선제 가동 (SSOT 체크)
        if self.sync_port and not force_refresh:
            print("[Service] Smart sync checking on Google Drive (SSOT)...")
            try:
                # (1) 종합 JSON 데이터베이스 스마트 다운로드
                self.sync_port.sync_down_if_newer(
                    remote_name="stock_splits_with_history.json",
                    local_path="data/stock_splits_with_history.json"
                )
                # (2) 현년 엑셀 시트 스마트 다운로드
                self.sync_port.sync_down_if_newer(
                    remote_name=f"액면분할({current_year}년).xlsx",
                    local_path=f"data/액면분할({current_year}년).xlsx"
                )
                print("[Service] Smart sync download check completed.")
            except Exception as se:
                print(f"[Service] [WARNING] Smart sync download failed (Continuing with local): {se}")

        # 2. 아웃바운드 포트를 사용하여 공시 목록 메타데이터 수집
        disclosures_meta = self.scraper_port.fetch_disclosures(
            start_date=start_date,
            end_date=end_date,
            keyword=keyword,
            exclude_corrections=exclude_corrections
        )
        
        if not disclosures_meta:
            print("[Service] No disclosures found for the specified period.")
            # 신규 공시가 없더라도 로컬/클라우드 영속성 데이터를 정상 반환
            try:
                return self.reader_port.load_all()
            except Exception:
                return []

        # 중복 방지 및 복원 적재를 위한 접수번호 기준 맵 구성
        meta_map = {m["rcept_no"]: m for m in disclosures_meta}
        relation_map = {}

        print("[Service] Analyzing corrections and fetching history disclosures...")
        
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
                        print(f"  [Service] Restored missing parent disclosure: {meta['corp_name']} ({hist_rcp}) - Date: {p_reg_date}")

        # 전체 복원 완료된 공시 목록
        final_meta_list = list(meta_map.values())
        print(f"[Service] Final disclosures to process (including restored): {len(final_meta_list)}")

        # 3. 개별 공시 상세 내용 파싱 및 도메인 모델 생성
        final_disclosures: List[StockSplitDisclosure] = []
        
        for i, meta in enumerate(final_meta_list, 1):
            corp_name = meta["corp_name"]
            rcept_no = meta["rcept_no"]
            reg_date = meta["reg_date"]
            
            print(f"[Service] [{i}/{len(final_meta_list)}] Parsing detail for {corp_name} ({rcept_no})...")
            
            # 아웃바운드 포트를 사용하여 공시 XML 본문 분석
            detail = self.parser_port.parse_split_info(rcept_no, force_refresh=force_refresh)
            
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
            except Exception as ve:
                print(f"  [Service] [WARNING] Validation error (skipped): {ve}")
                continue

        # 4. 정정공시 간의 최초 원본 공시일 계산 및 부모-자식 관계 맵핑 설정 (도메인 Aggregate 위임)
        if final_disclosures:
            print("[Service] Resolving original dates using domain Aggregate...")
            chain = StockSplitDisclosureChain(disclosures=final_disclosures, relation_map=relation_map)
            chain.resolve_original_dates()

        # 5. 기존 데이터베이스 로드 (증분 수집 및 머지 지원)
        existing_disclosures = []
        try:
            existing_disclosures = self.reader_port.load_all()
        except Exception as e:
            print(f"[Service] [WARNING] Failed to load existing disclosures: {e}")

        # 6. 기존 데이터와 신규 수집 데이터 병합 (접수번호 기준 중복 배제)
        disclosure_map = {d.rcept_no: d for d in existing_disclosures}
        for d in final_disclosures:
            disclosure_map[d.rcept_no] = d  # 신규 데이터로 덮어쓰기 (UPSERT)
            
        merged_disclosures = list(disclosure_map.values())
        
        # 7. 전체 병합 데이터 정렬 (공시 등록일 내림차순, 동일할 시 회사명 내림차순)
        merged_disclosures.sort(key=lambda x: (x.reg_date or "", x.corp_name or ""), reverse=True)

        # 8. 아웃바운드 포트를 사용하여 복합 영속화 실행
        if merged_disclosures:
            print(f"[Service] Saving {len(merged_disclosures)} merged disclosures (Existing: {len(existing_disclosures)}, New: {len(final_disclosures)})...")
            self.writer_port.save_all(merged_disclosures)
            
            # 9. 아웃바운드 포트를 사용하여 구글 드라이브 클라우드 동기화 업로드 기동
            if self.sync_port:
                print("[Service] Commencing smart sync upload to Google Drive...")
                try:
                    # (1) 로컬 디렉토리에 동적으로 생성된 엑셀 파일들 클라우드 업로드
                    excel_files = [
                        ("data/stock_splits_with_history.xlsx", "stock_splits_with_history.xlsx"),
                        (f"data/액면분할({current_year}년).xlsx", f"액면분할({current_year}년).xlsx"),
                        (f"data/액면분할({current_year - 1}년).xlsx", f"액면분할({current_year - 1}년).xlsx"),
                        (f"data/액면분할({current_year - 2}년).xlsx", f"액면분할({current_year - 2}년).xlsx")
                    ]
                    
                    for local_path, remote_name in excel_files:
                        if os.path.exists(local_path):
                            self.sync_port.sync_up_file(
                                local_path=local_path,
                                remote_name=remote_name,
                                mime_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            )
                    print("[Service] Google Drive cloud sync completely succeeded!")
                except Exception as sync_err:
                    print(f"[Service] [ERROR] Cloud sync failed: {sync_err}")
            
            print("[Service] Pipeline successfully completed!")
        else:
            print("[Service] No disclosures to save.")
            
        return merged_disclosures


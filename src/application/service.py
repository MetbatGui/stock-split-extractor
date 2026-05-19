from typing import List
from domain.models import StockSplitDisclosure
from ports.scraper import StockSplitScraperPort
from ports.parser import StockSplitParserPort
from ports.repository import StockSplitRepositoryPort

class StockSplitCollectionService:
    """
    주식분할결정 공시 수집 유스케이스를 관장하는 애플리케이션 서비스
    
    헥사고날 아키텍처의 원칙에 따라 구체 기술(어댑터)에 의존하지 않고, 
    생성자 주입(DI)을 통해 포트 인터페이스들만 결합하여 비즈니스 흐름을 제어합니다.
    """

    def __init__(
        self,
        scraper_port: StockSplitScraperPort,
        parser_port: StockSplitParserPort,
        repository_port: StockSplitRepositoryPort
    ) -> None:
        self.scraper_port = scraper_port
        self.parser_port = parser_port
        self.repository_port = repository_port

    def collect_splits_for_period(
        self, 
        start_date: str, 
        end_date: str, 
        keyword: str = "주식분할결정",
        exclude_corrections: bool = True
    ) -> List[StockSplitDisclosure]:
        """
        특정 기간 동안의 주식분할결정 공시들을 전체 수집, 본문 파싱, 데이터 검증 후 
        영속화 저장소에 저장하는 통합 비즈니스 흐름을 오케스트레이션합니다.
        
        Args:
            start_date: 시작일 (YYYYMMDD)
            end_date: 종료일 (YYYYMMDD)
            keyword: 검색할 서류명
            exclude_corrections: 정정공시 제외 여부
            
        Returns:
            유효성 검증을 통과한 통합 도메인 모델 객체 리스트
        """
        print(f"[Service] Pipeline started for period: {start_date} ~ {end_date}")
        
        # 1. 아웃바운드 포트를 사용하여 공시 목록 메타데이터 수집
        disclosures_meta = self.scraper_port.fetch_disclosures(
            start_date=start_date,
            end_date=end_date,
            keyword=keyword,
            exclude_corrections=exclude_corrections
        )
        
        if not disclosures_meta:
            print("[Service] No disclosures found for the specified period.")
            return []

        print(f"[Service] Found {len(disclosures_meta)} disclosures. Starting detail parsing...")

        # 2. 개별 공시 상세 내용 파싱 및 도메인 모델 생성
        final_disclosures: List[StockSplitDisclosure] = []
        
        for i, meta in enumerate(disclosures_meta, 1):
            corp_name = meta["corp_name"]
            rcept_no = meta["rcept_no"]
            reg_date = meta["reg_date"]
            
            print(f"[Service] [{i}/{len(disclosures_meta)}] Parsing detail for {corp_name} ({rcept_no})...")
            
            # 아웃바운드 포트를 사용하여 공시 XML 본문 분석
            detail = self.parser_port.parse_split_info(rcept_no)
            
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
                    pre_split_common_shares=detail["pre_split_common_shares"],
                    post_split_common_shares=detail["post_split_common_shares"],
                    new_share_listing_date=detail["new_share_listing_date"],
                    board_resolution_date=detail["board_resolution_date"]
                )
                final_disclosures.append(disclosure_obj)
            except Exception as ve:
                print(f"  [Service] [WARNING] Validation error (skipped): {ve}")
                continue

        # 3. 아웃바운드 포트를 사용하여 데이터 영속화
        if final_disclosures:
            print(f"[Service] Saving {len(final_disclosures)} valid disclosures...")
            self.repository_port.save_all(final_disclosures)
            print("[Service] Pipeline successfully completed!")
        else:
            print("[Service] No valid disclosures to save.")
            
        return final_disclosures

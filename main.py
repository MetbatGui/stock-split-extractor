import os
import re
import argparse
from datetime import datetime, timedelta
from adapters.scraper.dart_web_scraper import DartWebScraperAdapter
from adapters.parser.opendart_xml_parser import OpenDartXmlParserAdapter
from adapters.repository.local_json_repository import LocalJsonStockSplitRepositoryAdapter
from adapters.repository.local_excel_repository import LocalExcelStockSplitRepositoryAdapter
from adapters.repository.google_drive_repository import GoogleDriveStockSplitRepositoryAdapter
from adapters.repository.composite_repository import CompositeStockSplitWriterAdapter
from application.service import StockSplitCollectionService

def load_env_var(var_name: str) -> str:
    """.env 파일에서 특정 환경 변수 값을 안전하게 파싱해 옵니다."""
    if not os.path.exists(".env"):
        return ""
    with open(".env", "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(f"{var_name}\\s*=\\s*(.+)", content)
    if match:
        return match.group(1).strip().strip('"').strip("'")
    return ""

def main() -> None:
    # 0. CLI 실행 파라미터 분석 (--refresh, --days 지원)
    parser = argparse.ArgumentParser(description="주식분할 공시 수집기 파이프라인")
    parser.add_argument("--refresh", action="store_true", help="로컬 캐시 XML 파일을 무시하고 DART API에서 최신 데이터를 실시간 강제 재다운로드합니다.")
    parser.add_argument("--days", type=int, default=7, help="수집할 최근 일수 범위를 지정합니다 (기본값: 7일)")
    args, unknown = parser.parse_known_args()
    force_refresh = args.refresh
    days_range = args.days

    # 1. 대상 기간 설정 (실행일 기준 동적 범위 설정, 기본 최근 7일)
    end_date_obj = datetime.now()
    start_date_obj = end_date_obj - timedelta(days=days_range)
    
    start_date = start_date_obj.strftime("%Y%m%d")
    end_date = end_date_obj.strftime("%Y%m%d")
    
    print("=" * 60)
    print(">>> 헥사고날 기반 주식분할 공시 파이프라인 (Local JSON/Excel + GDrive SSOT)")
    print(f"[*] 대상 기간: {start_date_obj.strftime('%Y-%m-%d')} ~ {end_date_obj.strftime('%Y-%m-%d')} ({days_range}일간)")
    if force_refresh:
        print("[!] 알림: --refresh 플래그가 감지되었습니다. 로컬 캐시를 무시하고 실시간 재수집합니다.")
    print("=" * 60)

    # .env 환경 변수 확인 (GOOGLE_STOCK_SPLIT_FOLDER_ID 우선 조회)
    gdrive_folder_id = load_env_var("GOOGLE_STOCK_SPLIT_FOLDER_ID") or load_env_var("GOOGLE_DRIVE_FOLDER_ID")
    if not gdrive_folder_id:
        print("[WARNING] .env 파일에 GOOGLE_STOCK_SPLIT_FOLDER_ID가 정의되지 않았습니다.")
        print("          구글 드라이브 동기화를 이용하려면 .env에 GOOGLE_STOCK_SPLIT_FOLDER_ID 값을 추가해 주세요.")

    # 2. 개별 어댑터 인스턴스화
    scraper_adapter = DartWebScraperAdapter()
    parser_adapter = OpenDartXmlParserAdapter(cache_dir="cache")
    local_json_repository = LocalJsonStockSplitRepositoryAdapter(file_path="data/stock_splits_with_history.json")
    local_excel_repository = LocalExcelStockSplitRepositoryAdapter(file_path="data/stock_splits_with_history.xlsx")

    gdrive_repository_adapter = None
    if gdrive_folder_id:
        try:
            gdrive_repository_adapter = GoogleDriveStockSplitRepositoryAdapter(
                folder_id=gdrive_folder_id,
                file_name="stock_splits_with_history.json",
                credentials_path="secrets/client_secret.json",
                token_path="secrets/token.json"
            )
        except Exception as e:
            print(f"[SSOT] [WARNING] 구글 드라이브 인증 초기화 실패 (로컬 우선 가동): {e}")

    # 3. Composite Writer 구성 (다중 영속화 캡슐화)
    writers = [local_json_repository, local_excel_repository]
    if gdrive_repository_adapter:
        writers.append(gdrive_repository_adapter)
    composite_writer = CompositeStockSplitWriterAdapter(writers=writers)

    # 4. 비즈니스 서비스 생성 및 포트 결합 (DIP 완성)
    collection_service = StockSplitCollectionService(
        scraper_port=scraper_adapter,
        parser_port=parser_adapter,
        reader_port=local_json_repository,
        writer_port=composite_writer,
        sync_port=gdrive_repository_adapter
    )

    # 5. 파이프라인 통합 가동 (단 1회 호출로 오케스트레이션 수행)
    final_disclosures = collection_service.collect_splits_for_period(
        start_date=start_date,
        end_date=end_date,
        keyword="주식분할결정",
        exclude_corrections=False,
        force_refresh=force_refresh
    )

    # 6. 최종 수집 리포트 터미널 출력
    print("\n" + "=" * 60)
    print(f"[SUCCESS] 파이프라인 가동 완료: 총 {len(final_disclosures)}건 처리")
    print("=" * 60)

    if not final_disclosures:
        print("성공한 데이터가 없습니다.")
        return

    # 결과 데이터 표 출력
    print(f"{'회사명':<10} | {'분할비율':<6} | {'분할전 주식수':<14} | {'분할후 주식수':<14} | {'신주상장일':<10} | {'이사회결의일':<10}")
    print("-" * 85)
    for disc in final_disclosures[:15]:
        if disc.status == "철회":
            ratio = "철회"
            before = "철회"
            after = "철회"
            listing = "철회"
            board = "철회"
        else:
            ratio = f"{disc.split_ratio}배" if disc.split_ratio else "N/A"
            before = f"{disc.pre_split_common_shares:,}" if disc.pre_split_common_shares is not None else "N/A"
            after = f"{disc.post_split_common_shares:,}" if disc.post_split_common_shares is not None else "N/A"
            listing = disc.new_share_listing_date or "N/A"
            board = disc.board_resolution_date or "N/A"
        
        print(f"{disc.corp_name:<10} | {ratio:<6} | {before:<14} | {after:<14} | {listing:<10} | {board:<10}")

    if len(final_disclosures) > 15:
        print(f"... 외 {len(final_disclosures) - 15}건 추가 존재")
    print("=" * 60)

if __name__ == "__main__":
    main()

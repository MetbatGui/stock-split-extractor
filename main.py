import os
import re
from datetime import datetime, timedelta
from adapters.scraper.dart_web_scraper import DartWebScraperAdapter
from adapters.parser.opendart_xml_parser import OpenDartXmlParserAdapter
from adapters.repository.local_json_repository import LocalJsonStockSplitRepositoryAdapter
from adapters.repository.google_drive_repository import GoogleDriveStockSplitRepositoryAdapter
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
    # 1. 대상 기간 설정 (최근 1년: 2025.05.18 ~ 2026.05.18)
    end_date_obj = datetime(2026, 5, 18)  # 사용자의 현재 날짜 고정 참조
    start_date_obj = end_date_obj - timedelta(days=365)
    
    start_date = start_date_obj.strftime("%Y%m%d")
    end_date = end_date_obj.strftime("%Y%m%d")
    
    print("=" * 60)
    print(">>> 헥사고날 기반 주식분할 공시 파이프라인 (Local Backup + GDrive SSOT)")
    print(f"[*] 대상 기간: {start_date_obj.strftime('%Y-%m-%d')} ~ {end_date_obj.strftime('%Y-%m-%d')}")
    print("=" * 60)

    # .env 환경 변수 확인
    gdrive_folder_id = load_env_var("GOOGLE_DRIVE_FOLDER_ID")
    if not gdrive_folder_id:
        print("[WARNING] .env 파일에 GOOGLE_DRIVE_FOLDER_ID가 정의되지 않았습니다.")
        print("          구글 드라이브 동기화를 이용하려면 .env에 GOOGLE_DRIVE_FOLDER_ID 값을 추가해 주세요.")

    # 2. 어댑터 인스턴스화
    scraper_adapter = DartWebScraperAdapter()
    parser_adapter = OpenDartXmlParserAdapter(cache_dir="cache")
    local_repository_adapter = LocalJsonStockSplitRepositoryAdapter(file_path="data/stock_splits_1year.json")

    # 3. 비즈니스 서비스 생성 및 의존성 주입 (1차 로컬 백업 리포지토리)
    collection_service = StockSplitCollectionService(
        scraper_port=scraper_adapter,
        parser_port=parser_adapter,
        repository_port=local_repository_adapter
    )

    # 4. 1차 로컬 백업 파이프라인 가동 (안정적 데이터 수집 확보)
    final_disclosures = collection_service.collect_splits_for_period(
        start_date=start_date,
        end_date=end_date,
        keyword="주식분할결정",
        exclude_corrections=True
    )

    # 5. 2차 구글 드라이브 SSOT 업로드 동기화 (책임 분리형 어댑터 개별 호출)
    if final_disclosures and gdrive_folder_id:
        print("\n" + "-" * 60)
        print("[SSOT] 구글 드라이브 클라우드 업로드 동기화를 시작합니다...")
        
        try:
            # 구글 드라이브용 독립 어댑터 생성
            gdrive_repository_adapter = GoogleDriveStockSplitRepositoryAdapter(
                folder_id=gdrive_folder_id,
                file_name="stock_splits_1year.json",
                credentials_path="secrets/client_secret.json",
                token_path="secrets/token.json"
            )
            
            # 클라우드 동기화 수행
            gdrive_repository_adapter.save_all(final_disclosures)
            print("[SSOT] 구글 드라이브 클라우드 동기화 성공!")
        except FileNotFoundError as fnf_err:
            print(f"\n[SSOT] [ERROR] 구글 드라이브 업로드 실패: {fnf_err}")
            print("        ➡️ 'secrets/client_secret.json' 파일이 필요합니다.")
        except Exception as sync_err:
            print(f"\n[SSOT] [ERROR] 구글 드라이브 동기화 중 에러가 발생했습니다: {sync_err}")
        print("-" * 60)

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

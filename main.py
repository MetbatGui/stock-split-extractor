import argparse
from datetime import datetime, timedelta
import sys
import os

# src 디렉토리를 검색 경로 최상단에 확보
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from infrastructure.container import container

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
    print(">>> 헥사고날 기반 주식분할 공시 파이프라인 (DI Container 통합 운영)")
    print(f"[*] 대상 기간: {start_date_obj.strftime('%Y-%m-%d')} ~ {end_date_obj.strftime('%Y-%m-%d')} ({days_range}일간)")
    if force_refresh:
        print("[!] 알림: --refresh 플래그가 감지되었습니다. 로컬 캐시를 무시하고 실시간 재수집합니다.")
    print("=" * 60)

    # 2. DI 컨테이너를 통해 싱글톤 서비스 획득
    collection_service = container.collection_service

    # 3. 파이프라인 통합 가동 (단 1회 호출로 오케스트레이션 수행)
    final_disclosures = collection_service.collect_splits_for_period(
        start_date=start_date,
        end_date=end_date,
        keyword="주식분할결정",
        exclude_corrections=False,
        force_refresh=force_refresh
    )

    # 4. 최종 수집 리포트 터미널 출력
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

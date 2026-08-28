import os
import json
from datetime import datetime
from typing import List, Dict
from domain.models import StockSplitDisclosure
from ports.repository import StockSplitReaderPort, StockSplitWriterPort

class LocalJsonStockSplitRepositoryAdapter(StockSplitReaderPort, StockSplitWriterPort):
    """
    수집 완료된 공시들의 존재 유무, 최신 동기화 시각, 연도별 인덱스 메타데이터를 
    초경량 JSON 매니페스트 형태로 로컬 디스크 파일시스템에 관리하는 어댑터 (Reader 및 Writer 구현체)
    """

    def __init__(self, file_path: str = "data/stock_splits_manifest.json") -> None:
        self.file_path = file_path
        # 부모 디렉토리 생성 확인
        dir_name = os.path.dirname(self.file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def save_all(self, disclosures: List[StockSplitDisclosure]) -> None:
        """
        도메인 모델 리스트에서 상세 내용을 축소하고 경량화된 고유 인덱스 메타데이터만 
        매니페스트 구조로 전환하여 저장합니다.
        """
        # 연도별로 분류된 접수번호 매핑 구성
        by_year: Dict[str, List[str]] = {}
        disclosures_map = {}

        for disc in disclosures:
            year = disc.reg_date[:4] if disc.reg_date and len(disc.reg_date) >= 4 else "unknown"
            if year not in by_year:
                by_year[year] = []
            if disc.rcept_no not in by_year[year]:
                by_year[year].append(disc.rcept_no)

            # 경량화된 공시 최소 메타데이터 (상세 내역 제거)
            disclosures_map[disc.rcept_no] = {
                "corp_name": disc.corp_name,
                "report_nm": disc.report_nm,
                "reg_date": disc.reg_date,
                "original_reg_date": disc.original_reg_date or disc.reg_date,
                "parent_rcept_no": disc.parent_rcept_no,
                "is_cancelled": disc.is_cancelled,
                "split_ratio": disc.split_ratio,
                "status": disc.status
            }

        manifest_data = {
            "manifest_version": "1.0.0",
            "last_updated": datetime.now().isoformat(),
            "total_records": len(disclosures),
            "supported_years": sorted(list(by_year.keys())),
            "years_index": by_year,
            "disclosures": disclosures_map
        }

        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, ensure_ascii=False, indent=4)
            
        print(f"[RepositoryAdapter] Successfully saved Manifest with {len(disclosures)} records to {self.file_path}")

    def load_all(self) -> List[StockSplitDisclosure]:
        """
        매니페스트 JSON 파일을 읽어 기존 공시들의 핵심 식별 객체 리스트로 역직렬화합니다.
        상세 내역(보통주식수 등)은 엑셀 파일 복원을 유도하거나, 매니페스트에 보관된 기본 메타데이터로 객체를 재구성합니다.
        """
        if not os.path.exists(self.file_path):
            print(f"[RepositoryAdapter] No existing manifest file found at {self.file_path}. Returning empty list.")
            return []
            
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            
            disclosures_map = manifest_data.get("disclosures", {})
            disclosures = []
            
            for rcp_no, item in disclosures_map.items():
                # 매니페스트 복원 객체 생성 (엑셀의 상세 정보를 제외한 수집 유효성 대조용 스터브 역할)
                disclosures.append(StockSplitDisclosure(
                    corp_name=item["corp_name"],
                    report_nm=item["report_nm"],
                    rcept_no=rcp_no,
                    presenter=item.get("presenter", "-"),
                    reg_date=item["reg_date"],
                    is_cancelled=item["is_cancelled"],
                    parent_rcept_no=item.get("parent_rcept_no"),
                    original_reg_date=item.get("original_reg_date"),
                    pre_split_common_shares=None,
                    post_split_common_shares=None,
                    new_share_listing_date=None,
                    board_resolution_date=None
                ))
            
            print(f"[RepositoryAdapter] Successfully loaded {len(disclosures)} disclosures from Manifest: {self.file_path}")
            return disclosures
        except Exception as e:
            print(f"[RepositoryAdapter] [ERROR] Failed to load disclosures from Manifest: {e}")
            return []



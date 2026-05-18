import os
import json
from typing import List
from domain.models import StockSplitDisclosure
from ports.repository import StockSplitRepositoryPort

class LocalJsonStockSplitRepositoryAdapter(StockSplitRepositoryPort):
    """
    수집 완료된 도메인 모델 데이터를 로컬 디스크 파일시스템에 
    UTF-8 JSON 파일 형태로 저장하는 어댑터 (StockSplitRepositoryPort 구현체)
    """

    def __init__(self, file_path: str = "data/stock_splits_1year.json") -> None:
        self.file_path = file_path
        # 부모 디렉토리 생성 확인
        dir_name = os.path.dirname(self.file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def save_all(self, disclosures: List[StockSplitDisclosure]) -> None:
        """
        도메인 모델 리스트를 dict 리스트로 변환하여 디스크에 예쁘게 저장합니다.
        """
        data_to_save = [disc.model_dump() for disc in disclosures]
        
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
            
        print(f"[RepositoryAdapter] Successfully saved {len(disclosures)} disclosures to {self.file_path}")

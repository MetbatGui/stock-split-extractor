import os
import json
from typing import List
from domain.models import StockSplitDisclosure
from ports.repository import StockSplitReaderPort, StockSplitWriterPort

class LocalJsonStockSplitRepositoryAdapter(StockSplitReaderPort, StockSplitWriterPort):
    """
    수집 완료된 도메인 모델 데이터를 로컬 디스크 파일시스템에 
    UTF-8 JSON 파일 형태로 저장하고 로드하는 어댑터 (Reader 및 Writer 구현체)
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

    def load_all(self) -> List[StockSplitDisclosure]:
        """
        저장된 JSON 파일을 읽어 도메인 모델 리스트로 역직렬화합니다.
        """
        if not os.path.exists(self.file_path):
            print(f"[RepositoryAdapter] No existing database file found at {self.file_path}. Returning empty list.")
            return []
            
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            disclosures = []
            for item in data:
                disclosures.append(StockSplitDisclosure(**item))
            
            print(f"[RepositoryAdapter] Successfully loaded {len(disclosures)} disclosures from {self.file_path}")
            return disclosures
        except Exception as e:
            print(f"[RepositoryAdapter] [ERROR] Failed to load disclosures: {e}")
            return []


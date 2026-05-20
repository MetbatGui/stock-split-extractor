from abc import ABC, abstractmethod
from typing import List
from domain.models import StockSplitDisclosure

class StockSplitRepositoryPort(ABC):
    """
    수집 및 파싱 완료된 도메인 모델 데이터를 데이터 저장소에 영속화하는 아웃바운드 포트
    """
    
    @abstractmethod
    def save_all(self, disclosures: List[StockSplitDisclosure]) -> None:
        """
        도메인 객체 리스트를 저장소(JSON, DB 등)에 영속화합니다.
        """
        pass

    @abstractmethod
    def load_all(self) -> List[StockSplitDisclosure]:
        """
        저장소(JSON 등)에 보관된 기존 도메인 객체 리스트를 불러옵니다.
        """
        pass


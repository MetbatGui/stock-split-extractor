from abc import ABC, abstractmethod
from typing import List
from domain.models import StockSplitDisclosure

class StockSplitReaderPort(ABC):
    """저장소(JSON 등)에 보관된 기존 도메인 객체 리스트를 불러오는 인바운드/아웃바운드 포트"""
    
    @abstractmethod
    def load_all(self) -> List[StockSplitDisclosure]:
        pass


class StockSplitWriterPort(ABC):
    """수집 및 파싱 완료된 도메인 모델 데이터를 데이터 저장소에 영속화하는 아웃바운드 포트"""
    
    @abstractmethod
    def save_all(self, disclosures: List[StockSplitDisclosure]) -> None:
        pass


class CloudSyncPort(ABC):
    """
    원격 파일 클라우드와 로컬 파일 간의 스마트 동기화 및 
    양방향 동기화를 중재하는 아웃바운드 포트
    """
    
    @abstractmethod
    def sync_down_if_newer(self, remote_name: str, local_path: str) -> bool:
        """
        원격 클라우드 파일의 수정 시간과 로컬 파일 수정 시간을 대조하여,
        원격이 더 최신인 경우에만 실시간 로컬로 다운로드 및 시간 동기화를 수행합니다.
        """
        pass

    @abstractmethod
    def sync_up_file(self, local_path: str, remote_name: str, mime_type: str) -> None:
        """
        로컬에 생성된 파일(JSON, Excel 등)을 원격 드라이브 지정 폴더에 안전하게 업로드(덮어쓰기)합니다.
        """
        pass



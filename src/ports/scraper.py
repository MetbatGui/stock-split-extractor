from abc import ABC, abstractmethod
from typing import List, Dict, Any

class StockSplitScraperPort(ABC):
    """
    주식분할 공시 목록을 외부에서 수집해오는 아웃바운드 포트
    """
    
    @abstractmethod
    def fetch_disclosures(
        self, 
        start_date: str, 
        end_date: str, 
        keyword: str = "주식분할결정",
        exclude_corrections: bool = True
    ) -> List[Dict[str, Any]]:
        """
        특정 기간 동안의 공시 기본 메타데이터 목록을 수집하여 반환합니다.
        
        Args:
            start_date: 시작일 (YYYYMMDD)
            end_date: 종료일 (YYYYMMDD)
            keyword: 검색할 서류명
            exclude_corrections: 기재정정 공시를 제외할지 여부
        """
        pass

    @abstractmethod
    def get_history_rcp_list(self, rcp_no: str) -> List[str]:
        """
        주어진 공시의 DART 뷰어 페이지에서 관련 공시(이력) 접수번호들을 추출하여 오름차순 반환합니다.
        """
        pass

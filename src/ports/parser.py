from abc import ABC, abstractmethod
from typing import Dict, Any

class StockSplitParserPort(ABC):
    """
    접수번호에 해당하는 상세 공시 본문을 파싱하여 4대 핵심 데이터를 추출하는 아웃바운드 포트
    """
    
    @abstractmethod
    def parse_split_info(self, rcept_no: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        공시 접수번호를 기반으로 본문 XML을 다운로드 및 분석하여 주식분할 상세 수치 데이터를 반환합니다.
        
        Args:
            rcept_no: DART 공시 접수번호 (14자리 숫자)
            force_refresh: True 설정 시 로컬 캐시를 무시하고 실시간으로 DART API를 새로 재수집합니다.
            
        Returns:
            {
                "pre_split_common_shares": int or None,
                "post_split_common_shares": int or None,
                "new_share_listing_date": str or None,
                "board_resolution_date": str or None
            }
        """
        pass

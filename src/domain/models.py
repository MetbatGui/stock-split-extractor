from typing import Optional
from pydantic import BaseModel, Field, field_validator
import re

class StockSplitDisclosure(BaseModel):
    """
    주식분할결정 공시에 대한 도메인 모델 (통합 Flat 구조)
    
    DART 검색 목록에서 수집한 공시 메타데이터와 
    공시 상세 문서(XML)에서 파싱한 핵심 수치 데이터를 통합 관리합니다.
    """
    
    # 1. 공시 메타데이터 (DART 검색 단계)
    corp_name: str = Field(..., description="회사명 (예: 코미코)")
    report_nm: str = Field(..., description="공시명 (예: 주식분할결정)")
    rcept_no: str = Field(..., description="공시 접수번호 (14자리 숫자 문자열)")
    presenter: str = Field(..., description="공시 제출인")
    reg_date: str = Field(..., description="공시 접수일자 (형식: YYYY.MM.DD)")
    
    # 2. 주식분할 상세 데이터 (XML 본문 파싱 단계)
    pre_split_common_shares: Optional[int] = Field(None, description="분할 전 보통주식 수 (주)")
    post_split_common_shares: Optional[int] = Field(None, description="분할 후 보통주식 수 (주)")
    new_share_listing_date: Optional[str] = Field(None, description="신주권상장예정일 (형식: YYYY-MM-DD)")
    board_resolution_date: Optional[str] = Field(None, description="이사회결의일 (형식: YYYY-MM-DD)")

    # 3. 유효성 검증 및 전처리 로직 (Validators)
    
    @field_validator("reg_date")
    @classmethod
    def validate_reg_date(cls, value: str) -> str:
        """접수일자 형식(YYYY.MM.DD) 유효성 검사 및 정규화"""
        value_clean = value.strip()
        # YYYY.MM.DD 또는 YYYY-MM-DD 둘 다 수용 후 YYYY.MM.DD로 정규화
        if re.match(r"^\d{4}\.\d{2}\.\d{2}$", value_clean):
            return value_clean
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", value_clean):
            return value_clean.replace("-", ".")
        raise ValueError("공시 접수일자는 YYYY.MM.DD 또는 YYYY-MM-DD 형식이어야 합니다.")

    @field_validator("new_share_listing_date", "board_resolution_date")
    @classmethod
    def validate_detail_dates(cls, value: Optional[str]) -> Optional[str]:
        """상세 날짜 필드(YYYY-MM-DD) 유효성 검사 및 정규화"""
        if value is None or value == "" or value == "-":
            return None
            
        value_clean = value.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value_clean):
            return value_clean
        elif re.match(r"^\d{4}\.\d{2}\.\d{2}$", value_clean):
            return value_clean.replace(".", "-")
        raise ValueError("날짜 필드는 YYYY-MM-DD 또는 YYYY.MM.DD 형식이어야 합니다.")

    @field_validator("pre_split_common_shares", "post_split_common_shares")
    @classmethod
    def validate_shares(cls, value: Optional[int]) -> Optional[int]:
        """주식 수 음수 값 방지 검증"""
        if value is not None and value < 0:
            raise ValueError("주식 수는 0보다 작을 수 없습니다.")
        return value

    # 4. 비즈니스 헬퍼 메서드 (Properties)
    
    @property
    def split_ratio(self) -> Optional[float]:
        """
        주식분할 비율을 계산하여 반환합니다.
        예: 3,518,595 -> 17,592,975주인 경우 5.0 (5배 분할)
        """
        if self.pre_split_common_shares and self.post_split_common_shares:
            return round(self.post_split_common_shares / self.pre_split_common_shares, 2)
        return None

    @property
    def is_split_ratio_standard(self) -> bool:
        """분할 비율이 정수배(예: 2배, 5배, 10배 등)인지 여부 판단"""
        ratio = self.split_ratio
        if ratio is None:
            return False
        return ratio.is_integer()

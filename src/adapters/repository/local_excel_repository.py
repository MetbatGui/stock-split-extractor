import os
import pandas as pd  # type: ignore
from typing import List
from domain.models import StockSplitDisclosure
from ports.repository import StockSplitRepositoryPort

class LocalExcelStockSplitRepositoryAdapter(StockSplitRepositoryPort):
    """
    수집 완료된 도메인 모델 데이터를 프리미엄 스타일이 적용된 
    Excel 파일 형태로 로컬 디스크에 저장하는 어댑터 (StockSplitRepositoryPort 구현체)
    """

    def __init__(self, file_path: str = "data/stock_splits_1year.xlsx") -> None:
        self.file_path = file_path
        # 부모 디렉토리 자동 생성
        dir_name = os.path.dirname(self.file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def save_all(self, disclosures: List[StockSplitDisclosure]) -> None:
        """
        도메인 모델 리스트를 판다스 DataFrame으로 변환하고, 
        열 너비 자동 맞춤이 적용된 고급 엑셀 파일로 디스크에 저장합니다.
        """
        if not disclosures:
            print("[ExcelAdapter] No disclosures to save. Excel creation skipped.")
            return

        # 1. 도메인 모델 리스트를 사전 리스트 형식으로 전환
        raw_data = []
        for disc in disclosures:
            raw_data.append({
                "회사명": disc.corp_name,
                "공시명": disc.report_nm,
                "접수번호": disc.rcept_no,
                "제출인": disc.presenter,
                "등록일자": disc.reg_date,
                "분할전 보통주식수(주)": disc.pre_split_common_shares,
                "분할후 보통주식수(주)": disc.post_split_common_shares,
                "분할배율": disc.split_ratio,
                "신주상장예정일": disc.new_share_listing_date,
                "이사회결의일": disc.board_resolution_date
            })

        # 2. DataFrame 생성
        df = pd.DataFrame(raw_data)

        # 3. ExcelWriter와 openpyxl 엔진을 사용하여 엑셀 작성 및 고급 스타일링
        sheet_name = "주식분할결정_최근1년"
        
        try:
            with pd.ExcelWriter(self.file_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                
                # 워크시트 객체 획득
                workbook = writer.book
                worksheet = workbook[sheet_name]
                
                # 프리미엄 스타일링 - 엑셀 열 너비 자동 보정 (Auto-fit Columns)
                # 한글 데이터의 문자 폭을 고려하여 동적으로 셀의 가로 폭을 연산하고 자동 확장합니다.
                for col in worksheet.columns:
                    max_len = 0
                    col_letter = col[0].column_letter  # 열 알파벳 (예: 'A', 'B' ...)
                    
                    for cell in col:
                        val = cell.value
                        if val is not None:
                            val_str = str(val)
                            # 한글(유니코드 한글 영역)은 2바이트 공간을 먹으므로 너비 연산 가중치(+1) 부여
                            actual_len = 0
                            for char in val_str:
                                if ord(char) > 127:  # 한글 및 유니코드 다국어 문자
                                    actual_len += 2
                                else:
                                    actual_len += 1
                            if actual_len > max_len:
                                max_len = actual_len
                    
                    # 헤더 및 컨텐츠 길이에 기반해 적절한 마진(padding=4)을 준 열 너비 세팅
                    worksheet.column_dimensions[col_letter].width = max(max_len + 4, 12)
            
            print(f"[ExcelAdapter] Successfully saved {len(disclosures)} disclosures to EXCEL: {self.file_path}")
            
        except Exception as excel_err:
            print(f"[ExcelAdapter] [ERROR] Failed to save excel file: {excel_err}")
            raise excel_err

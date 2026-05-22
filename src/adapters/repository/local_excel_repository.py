import os
import pandas as pd
from typing import List
from domain.models import StockSplitDisclosure
from ports.repository import StockSplitWriterPort

class LocalExcelStockSplitRepositoryAdapter(StockSplitWriterPort):
    """
    수집 완료된 도메인 모델 데이터를 프리미엄 스타일이 적용된 
    Excel 파일 형태로 로컬 디스크에 저장하는 어댑터 (StockSplitWriterPort 구현체)
    """

    def __init__(self, file_path: str = "data/stock_splits_1year.xlsx") -> None:
        self.file_path = file_path
        # 부모 디렉토리 자동 생성
        dir_name = os.path.dirname(self.file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def save_all(self, disclosures: List[StockSplitDisclosure]) -> None:
        """
        도메인 모델 리스트를 종합 엑셀로 저장할 뿐만 아니라,
        공시년도별로 분할하여 '액면분할(YYYY년).xlsx' 형식의 별도 파일로 쪼개어 저장합니다.
        """
        if not disclosures:
            print("[ExcelAdapter] No disclosures to save. Excel creation skipped.")
            return

        # 부모 디렉토리 확보
        base_dir = os.path.dirname(self.file_path) or "data"

        # 1. 종합 엑셀 파일 저장 (기존 스펙 보존)
        self._save_to_file(disclosures, self.file_path, sheet_name="주식분할결정_종합")

        # 2. 연도별 분류 및 분할 저장
        by_year: dict[str, List[StockSplitDisclosure]] = {}
        for disc in disclosures:
            year = "미정"
            if disc.reg_date and len(disc.reg_date) >= 4:
                year = disc.reg_date[:4]  # YYYY 추출
            
            if year not in by_year:
                by_year[year] = []
            by_year[year].append(disc)

        for year, year_disclosures in by_year.items():
            year_file_path = os.path.join(base_dir, f"액면분할({year}년).xlsx")
            self._save_to_file(year_disclosures, year_file_path, sheet_name=f"주식분할결정_{year}년")

    def _save_to_file(self, disclosures: List[StockSplitDisclosure], target_path: str, sheet_name: str) -> None:
        """단일 엑셀 파일로 저장 및 프리미엄 너비 맞춤 처리를 하는 내부 헬퍼 메서드"""
        # 1. 도메인 모델 리스트를 사전 리스트 형식으로 전환
        raw_data = []
        for disc in disclosures:
            is_correction = "[기재정정]" if "정정" in disc.report_nm else ""
            parent_no = disc.parent_rcept_no if (disc.parent_rcept_no and "정정" in disc.report_nm) else ""

            raw_data.append({
                "회사명": disc.corp_name,
                "기재정정": is_correction,
                "철회여부": disc.status,
                "등록일자": disc.reg_date,
                "최초공시 등록일자": disc.original_reg_date or disc.reg_date,
                "공시번호": disc.rcept_no,
                "이전공시번호": parent_no,
                "분할전 보통주식수(주)": disc.pre_split_common_shares,
                "분할후 보통주식수(주)": disc.post_split_common_shares,
                "분할배율": disc.split_ratio,
                "신주상장예정일": disc.new_share_listing_date,
                "이사회결의일": disc.board_resolution_date
            })

        # 2. DataFrame 생성
        df = pd.DataFrame(raw_data)
        
        try:
            with pd.ExcelWriter(target_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                
                # 워크시트 객체 획득
                workbook = writer.book
                worksheet = workbook[sheet_name]
                
                # 프리미엄 스타일링 - 엑셀 열 너비 자동 보정 (Auto-fit Columns)
                for col in worksheet.columns:
                    max_len = 0
                    col_letter = col[0].column_letter
                    
                    for cell in col:
                        val = cell.value
                        if val is not None:
                            val_str = str(val)
                            # 한글은 너비 연산 가중치(+2) 부여
                            actual_len = 0
                            for char in val_str:
                                if ord(char) > 127:
                                    actual_len += 2
                                else:
                                    actual_len += 1
                            if actual_len > max_len:
                                max_len = actual_len
                    
                    worksheet.column_dimensions[col_letter].width = max(max_len + 4, 12)
            
            print(f"[ExcelAdapter] Successfully saved {len(disclosures)} disclosures to EXCEL: {target_path}")
            
        except Exception as excel_err:
            print(f"[ExcelAdapter] [ERROR] Failed to save excel file {target_path}: {excel_err}")
            raise excel_err

    # Excel 리포지토리는 ISP 원칙에 따라 읽기(ReaderPort) 기능을 별도 계약하지 않아 load_all을 구현하지 않습니다.



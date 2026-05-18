import os
import re
import zipfile
import io
from typing import Dict, Any, Optional
import requests
from bs4 import BeautifulSoup
from ports.parser import StockSplitParserPort

class OpenDartXmlParserAdapter(StockSplitParserPort):
    """
    OpenDART API를 통해 공시 원본 XML을 다운로드(캐싱 포함)하고 
    핵심 4대 데이터를 정밀 파싱하는 어댑터 (StockSplitParserPort 구현체)
    """

    def __init__(self, cache_dir: str = "cache") -> None:
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self.api_key = self._load_api_key()

    def _load_api_key(self) -> Optional[str]:
        """.env 파일에서 DART_API_KEY를 탐색하여 로드합니다."""
        if not os.path.exists(".env"):
            return None
        with open(".env", "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r"DART_API_KEY\s*=\s*([a-zA-Z0-9]+)", content)
        if match:
            return match.group(1).strip()
        return None

    def _clean_text(self, text: str) -> str:
        """텍스트 공백 정제"""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    def _get_xml_content(self, rcept_no: str) -> str:
        """로컬 캐시를 조회하거나 OpenDART API를 호출하여 XML 원본 본문을 가져옵니다."""
        xml_path = os.path.join(self.cache_dir, f"{rcept_no}.xml")
        
        # 1. 로컬 캐시 확인
        if os.path.exists(xml_path):
            with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

        # 2. OpenDART API 다운로드
        if not self.api_key:
            raise ValueError("DART_API_KEY not found in .env file. Unable to query OpenDART API.")

        url = "https://opendart.fss.or.kr/api/document.xml"
        params = {
            "crtfc_key": self.api_key,
            "rcept_no": rcept_no
        }

        response = requests.get(url, params=params)
        response.raise_for_status()

        # 에러 처리
        if response.headers.get("Content-Type", "").startswith("application/json") or b"status" in response.content:
            if response.content.startswith(b"<?xml") or response.content.startswith(b"{"):
                err_msg = response.content.decode("utf-8", errors="replace")
                raise RuntimeError(f"OpenDART API Error: {err_msg}")

        # ZIP 압축 해제 및 캐싱
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
                namelist = zip_ref.namelist()
                if not namelist:
                    raise RuntimeError("Downloaded ZIP file is empty.")
                
                xml_filename = namelist[0]
                extracted_data = zip_ref.read(xml_filename).decode("utf-8", errors="replace")
                
                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(extracted_data)
                
                return extracted_data
        except zipfile.BadZipFile:
            err_head = response.content.decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"Failed to parse downloaded content as ZIP. Response starts with: {err_head}")

    def parse_split_info(self, rcept_no: str) -> Dict[str, Any]:
        """주식분할결정 XML 공시에서 4대 수치 지표를 강건하게 파싱합니다."""
        result: Dict[str, Any] = {
            "pre_split_common_shares": None,
            "post_split_common_shares": None,
            "new_share_listing_date": None,
            "board_resolution_date": None
        }

        try:
            xml_content = self._get_xml_content(rcept_no)
        except Exception as e:
            print(f"[ParserAdapter] Error fetching document {rcept_no}: {e}")
            return result

        soup = BeautifulSoup(xml_content, "html.parser")
        trs = soup.find_all("tr")

        date_pattern = r"\d{4}-\d{2}-\d{2}"

        for tr in trs:
            tr_text = self._clean_text(tr.get_text())

            # 1. 발행주식총수 보통주식(주) 전 / 후 파싱 (띄어쓰기 및 조사 개입 완충 정규식 적용)
            is_total_shares = re.search(r"발행\s*주식\s*(의)?\s*총수", tr_text)
            is_common_shares = re.search(r"보통\s*주식", tr_text)

            if is_total_shares and is_common_shares:
                inputs = tr.find_all(class_="xforms_input")
                share_numbers = []
                for inp in inputs:
                    inp_text = self._clean_text(inp.get_text()).replace(",", "")
                    if inp_text.isdigit() and len(inp_text) >= 4:
                        share_numbers.append(int(inp_text))

                if len(share_numbers) < 2:
                    all_numbers = re.findall(r"\d[\d,]*", tr_text)
                    share_numbers = []
                    for num in all_numbers:
                        num_clean = num.replace(",", "")
                        # 주식 수는 일반적으로 4자리 이상의 큰 수치임 (예외적 소형 번호 필터링)
                        if num_clean.isdigit() and len(num_clean) >= 4:
                            share_numbers.append(int(num_clean))

                if len(share_numbers) >= 2:
                    result["pre_split_common_shares"] = share_numbers[0]
                    result["post_split_common_shares"] = share_numbers[1]

            # 2. 신주권상장예정일 파싱
            elif "신주권상장예정일" in tr_text:
                date_match = re.search(date_pattern, tr_text)
                if date_match:
                    result["new_share_listing_date"] = date_match.group(0)
                else:
                    inputs = tr.find_all(class_="xforms_input")
                    for inp in inputs:
                        inp_text = self._clean_text(inp.get_text())
                        if re.match(date_pattern, inp_text):
                            result["new_share_listing_date"] = inp_text
                            break

            # 3. 이사회결의일 파싱
            elif "이사회결의일" in tr_text:
                date_match = re.search(date_pattern, tr_text)
                if date_match:
                    result["board_resolution_date"] = date_match.group(0)
                else:
                    inputs = tr.find_all(class_="xforms_input")
                    for inp in inputs:
                        inp_text = self._clean_text(inp.get_text())
                        if re.match(date_pattern, inp_text):
                            result["board_resolution_date"] = inp_text
                            break

        return result

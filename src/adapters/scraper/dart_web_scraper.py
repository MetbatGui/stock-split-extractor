import re
import time
import random
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
from ports.scraper import StockSplitScraperPort

class DartWebScraperAdapter(StockSplitScraperPort):
    """
    DART 상세 검색 페이지를 직접 웹 스크래핑하여 
    주식분할 공시 목록을 가져오는 어댑터 (StockSplitScraperPort 구현체)
    """

    def __init__(self) -> None:
        self.search_url = "https://dart.fss.or.kr/dsab007/detailSearch.ax"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "Referer": "https://dart.fss.or.kr/dsab007/main.do",
            "Origin": "https://dart.fss.or.kr",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/html, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        self.session = requests.Session()

    def _clean_text(self, text: str) -> str:
        """텍스트 줄바꿈 및 불필요한 연속 공백 정제"""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    def fetch_disclosures(
        self, 
        start_date: str, 
        end_date: str, 
        keyword: str = "주식분할결정",
        exclude_corrections: bool = True
    ) -> List[Dict[str, Any]]:
        """
        DART 상세 검색 POST 요청을 이용해 특정 기간 동안의 공시 목록을 대량 수집 및 페이지네이션 병합합니다.
        """
        all_disclosures: List[Dict[str, Any]] = []
        page = 1
        max_results = 100  # 한 번에 크게 수집
        
        # 날짜 포맷 정리 (YYYY.MM.DD 또는 YYYY-MM-DD -> YYYYMMDD)
        start_date_clean = start_date.replace(".", "").replace("-", "")
        end_date_clean = end_date.replace(".", "").replace("-", "")

        print(f"[ScraperAdapter] Scraping DART disclosures for '{keyword}'...")

        while True:
            payload = {
                "currentPage": str(page),
                "maxResults": str(max_results),
                "maxLinks": "10",
                "sort": "date",
                "series": "desc",
                "textCrpCik": "",
                "lateKeyword": "",
                "keyword": "",
                "reportNamePopYn": "Y",
                "textkeyword": "",
                "businessCode": "all",
                "autoSearch": "N",
                "autoSearchCorp": "Y",
                "option": "report",
                "textCrpNm": "",
                "reportName": keyword,
                "tocSrch": "",
                "textCrpNm2": "",
                "textPresenterNm": "",
                "startDate": start_date_clean,
                "endDate": end_date_clean,
                "decadeType": "",
                "finalReport": "recent",
                "businessNm": "전체",
                "corporationType": "all",
                "closingAccountsMonth": "all",
                "tocSrch2": ""
            }

            # 레이트 리밋 우회를 위한 임의 딜레이
            time.sleep(random.uniform(1.0, 1.8))
            
            response = self.session.post(self.search_url, data=payload, headers=self.headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            table = soup.find("table")
            if not table:
                break

            tbody = table.find("tbody")
            if not tbody:
                break

            trs = tbody.find_all("tr")
            if not trs:
                break

            page_results_count = 0
            for tr in trs:
                tds = tr.find_all("td")
                if len(tds) < 5:
                    continue
                
                page_results_count += 1
                
                # 1. 회사명 파싱 (시장 기호 예: '코 ', '유 ' 제거)
                corp_name_raw = tds[1].get_text()
                corp_name = self._clean_text(corp_name_raw)
                corp_name = re.sub(r"^(코|유|넥|외)\s+", "", corp_name)

                # 2. 공시명 및 접수번호 파싱
                report_td = tds[2]
                report_a = report_td.find("a")
                if not report_a:
                    continue
                
                report_nm = self._clean_text(report_a.get_text())
                href = str(report_a.get("href") or "").strip()
                
                rcp_no_match = re.search(r"rcpNo=(\d+)", href)
                rcept_no = rcp_no_match.group(1) if rcp_no_match else ""
                
                if not rcept_no:
                    continue

                # 기재정정 공시 필터링
                if exclude_corrections and ("[기재정정]" in report_nm or "정정" in report_nm):
                    continue

                # 3. 제출인 및 등록일자 파싱
                presenter = self._clean_text(tds[3].get_text())
                reg_date = self._clean_text(tds[4].get_text())

                all_disclosures.append({
                    "corp_name": corp_name,
                    "report_nm": report_nm,
                    "rcept_no": rcept_no,
                    "presenter": presenter,
                    "reg_date": reg_date
                })

            print(f"[ScraperAdapter] Page {page}: Scanned {page_results_count} items, collected {len(all_disclosures)} items.")

            # 가져온 총 결과 행 수가 요청 최대 개수(max_results)보다 작다면 마지막 페이지
            if page_results_count < max_results:
                break
                
            page += 1

        print(f"[ScraperAdapter] Scraping finished. Total: {len(all_disclosures)} items.")
        return all_disclosures

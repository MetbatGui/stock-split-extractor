import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from application.service import StockSplitCollectionService
from domain.models import StockSplitDisclosure


def _existing_disclosure(rcept_no: str) -> StockSplitDisclosure:
    return StockSplitDisclosure(
        corp_name="기존회사",
        report_nm="주식분할결정",
        rcept_no=rcept_no,
        presenter="기존회사",
        reg_date="2026.01.05",
        is_cancelled=False,
        pre_split_common_shares=1000,
        post_split_common_shares=2000,
        new_share_listing_date="2026-01-20",
        board_resolution_date="2026-01-01",
    )


class FakeScraperPort:
    def __init__(self, metas):
        self._metas = metas

    def fetch_disclosures(self, start_date, end_date, keyword="주식분할결정", exclude_corrections=True):
        return self._metas

    def get_history_rcp_list(self, rcp_no):
        return [rcp_no]


class FakeParserPort:
    def __init__(self):
        self.parsed_rcept_nos = []

    def parse_split_info(self, rcept_no, force_refresh=False):
        self.parsed_rcept_nos.append(rcept_no)
        return {
            "pre_split_common_shares": 1000,
            "post_split_common_shares": 3000,
            "new_share_listing_date": "2026-02-01",
            "board_resolution_date": "2026-01-15",
            "is_cancelled": False,
        }


class FakeReaderWriterPort:
    def __init__(self, existing):
        self._existing = existing
        self.saved = None

    def load_all(self):
        return list(self._existing)

    def save_all(self, disclosures):
        self.saved = list(disclosures)


def test_already_stored_rcept_no_is_not_reparsed():
    existing_rcept_no = "20260105000001"
    new_rcept_no = "20260110000002"

    scraper = FakeScraperPort(
        metas=[
            {
                "corp_name": "기존회사",
                "report_nm": "주식분할결정",
                "rcept_no": existing_rcept_no,
                "presenter": "기존회사",
                "reg_date": "2026.01.05",
            },
            {
                "corp_name": "신규회사",
                "report_nm": "주식분할결정",
                "rcept_no": new_rcept_no,
                "presenter": "신규회사",
                "reg_date": "2026.01.10",
            },
        ]
    )
    parser = FakeParserPort()
    repo = FakeReaderWriterPort(existing=[_existing_disclosure(existing_rcept_no)])

    service = StockSplitCollectionService(
        scraper_port=scraper,
        parser_port=parser,
        reader_port=repo,
        writer_port=repo,
        sync_port=None,
    )

    result = service.collect_splits_for_period(start_date="20260101", end_date="20260131")

    assert parser.parsed_rcept_nos == [new_rcept_no]
    assert result.skipped_existing == 1
    assert result.parsed == 1


def test_force_refresh_reparses_already_stored_rcept_no():
    existing_rcept_no = "20260105000001"

    scraper = FakeScraperPort(
        metas=[
            {
                "corp_name": "기존회사",
                "report_nm": "주식분할결정",
                "rcept_no": existing_rcept_no,
                "presenter": "기존회사",
                "reg_date": "2026.01.05",
            }
        ]
    )
    parser = FakeParserPort()
    repo = FakeReaderWriterPort(existing=[_existing_disclosure(existing_rcept_no)])

    service = StockSplitCollectionService(
        scraper_port=scraper,
        parser_port=parser,
        reader_port=repo,
        writer_port=repo,
        sync_port=None,
    )

    result = service.collect_splits_for_period(
        start_date="20260101", end_date="20260131", force_refresh=True
    )

    assert parser.parsed_rcept_nos == [existing_rcept_no]
    assert result.skipped_existing == 0

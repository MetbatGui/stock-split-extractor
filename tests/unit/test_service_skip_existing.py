import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from application.service import StockSplitCollectionService
from domain.models import StockSplitDisclosure


def _existing_disclosure(rcept_no: str, **overrides) -> StockSplitDisclosure:
    fields = dict(
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
    fields.update(overrides)
    return StockSplitDisclosure(**fields)


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


def test_skipped_disclosure_keeps_its_previously_resolved_original_reg_date():
    """정정 체인 해석으로 이미 계산해둔 original_reg_date/parent_rcept_no는,
    이번 실행에서 해당 공시가 스킵되면(완료 판정) relation_map에 안 잡히더라도
    자기 자신 날짜로 덮어써지면 안 된다."""
    child_rcept_no = "20260110000002"
    parent_rcept_no = "20260105000001"

    existing_child = _existing_disclosure(
        child_rcept_no,
        report_nm="[기재정정]주식분할결정",
        reg_date="2026.01.10",
        parent_rcept_no=parent_rcept_no,
        original_reg_date="2026.01.05",
    )

    scraper = FakeScraperPort(
        metas=[
            {
                "corp_name": "기존회사",
                "report_nm": "[기재정정]주식분할결정",
                "rcept_no": child_rcept_no,
                "presenter": "기존회사",
                "reg_date": "2026.01.10",
            }
        ]
    )
    parser = FakeParserPort()
    repo = FakeReaderWriterPort(existing=[existing_child])

    service = StockSplitCollectionService(
        scraper_port=scraper,
        parser_port=parser,
        reader_port=repo,
        writer_port=repo,
        sync_port=None,
    )

    result = service.collect_splits_for_period(start_date="20260101", end_date="20260131")

    saved = {d.rcept_no: d for d in result.disclosures}
    assert saved[child_rcept_no].original_reg_date == "2026.01.05"
    assert saved[child_rcept_no].parent_rcept_no == parent_rcept_no

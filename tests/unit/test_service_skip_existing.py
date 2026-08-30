import sys
import os
from unittest.mock import patch

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


class FailingSyncPort:
    def sync_down_if_newer(self, remote_name, local_path):
        return False

    def sync_up_file(self, local_path, remote_name, mime_type):
        raise RuntimeError("simulated Drive upload failure")


def test_result_reports_sync_up_failed_when_drive_upload_raises():
    """Drive 업로드가 실패하면 CollectionRunResult.sync_up_failed가 True여야 한다 -
    호출부(main.py)가 이걸로 exit code를 결정해 업로드 실패를 조용히 넘기지 않게 한다."""
    new_rcept_no = "20260110000002"
    scraper = FakeScraperPort(
        metas=[
            {
                "corp_name": "신규회사",
                "report_nm": "주식분할결정",
                "rcept_no": new_rcept_no,
                "presenter": "신규회사",
                "reg_date": "2026.01.10",
            }
        ]
    )
    parser = FakeParserPort()
    repo = FakeReaderWriterPort(existing=[])

    service = StockSplitCollectionService(
        scraper_port=scraper,
        parser_port=parser,
        reader_port=repo,
        writer_port=repo,
        sync_port=FailingSyncPort(),
    )

    with patch("application.service.os.path.exists", return_value=True):
        result = service.collect_splits_for_period(start_date="20260101", end_date="20260131")

    assert result.sync_up_failed is True


class PartiallyFailingSyncPort:
    """특정 remote_name 하나만 실패하고, 나머지는 시도돼야 한다는 걸 검증하기 위한 스텁."""

    def __init__(self, fail_remote_name):
        self._fail_remote_name = fail_remote_name
        self.attempted = []

    def sync_down_if_newer(self, remote_name, local_path):
        return False

    def sync_up_file(self, local_path, remote_name, mime_type):
        self.attempted.append(remote_name)
        if remote_name == self._fail_remote_name:
            raise RuntimeError(f"simulated failure for {remote_name}")


def test_one_failed_upload_does_not_block_remaining_uploads():
    """업로드 대상 하나가 실패해도 나머지 파일들은 계속 시도돼야 한다 - 예전엔 for 루프
    전체가 하나의 try에 묶여서 첫 실패가 나머지 업로드 시도 자체를 막았다."""
    new_rcept_no = "20260110000002"
    scraper = FakeScraperPort(
        metas=[
            {
                "corp_name": "신규회사",
                "report_nm": "주식분할결정",
                "rcept_no": new_rcept_no,
                "presenter": "신규회사",
                "reg_date": "2026.01.10",
            }
        ]
    )
    parser = FakeParserPort()
    repo = FakeReaderWriterPort(existing=[])
    sync_port = PartiallyFailingSyncPort(fail_remote_name="stock_splits.db")

    service = StockSplitCollectionService(
        scraper_port=scraper,
        parser_port=parser,
        reader_port=repo,
        writer_port=repo,
        sync_port=sync_port,
    )

    with patch("application.service.os.path.exists", return_value=True):
        result = service.collect_splits_for_period(start_date="20260101", end_date="20260131")

    assert result.sync_up_failed is True
    # DB 업로드가 실패해도 엑셀 3개는 전부 시도됐어야 한다 (총 4개 대상)
    assert len(sync_port.attempted) == 4
    assert "stock_splits.db" in sync_port.attempted


def test_excel_uploads_are_attempted_before_db_upload():
    """산출물(엑셀)이 DB보다 먼저 업로드돼야 한다 (db_ssot_guide.md §3)."""
    new_rcept_no = "20260110000002"
    scraper = FakeScraperPort(
        metas=[
            {
                "corp_name": "신규회사",
                "report_nm": "주식분할결정",
                "rcept_no": new_rcept_no,
                "presenter": "신규회사",
                "reg_date": "2026.01.10",
            }
        ]
    )
    parser = FakeParserPort()
    repo = FakeReaderWriterPort(existing=[])
    sync_port = PartiallyFailingSyncPort(fail_remote_name="__never__")

    service = StockSplitCollectionService(
        scraper_port=scraper,
        parser_port=parser,
        reader_port=repo,
        writer_port=repo,
        sync_port=sync_port,
    )

    with patch("application.service.os.path.exists", return_value=True):
        service.collect_splits_for_period(start_date="20260101", end_date="20260131")

    assert sync_port.attempted[-1] == "stock_splits.db"
    assert all(name.endswith(".xlsx") for name in sync_port.attempted[:-1])

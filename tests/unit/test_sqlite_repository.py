import sys
import os
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from adapters.repository.sqlite_repository import SqliteStockSplitRepositoryAdapter
from domain.models import StockSplitDisclosure


def _make_disclosure(rcept_no: str, corp_name: str = "코미코") -> StockSplitDisclosure:
    return StockSplitDisclosure(
        corp_name=corp_name,
        report_nm="주식분할결정",
        rcept_no=rcept_no,
        presenter=corp_name,
        reg_date="2026.01.15",
        is_cancelled=False,
        parent_rcept_no=None,
        original_reg_date=None,
        pre_split_common_shares=1000,
        post_split_common_shares=5000,
        new_share_listing_date="2026-02-01",
        board_resolution_date="2026-01-10",
    )


def test_save_all_then_load_all_roundtrip(tmp_path):
    db_path = tmp_path / "stock_splits.db"
    repo = SqliteStockSplitRepositoryAdapter(db_path=str(db_path))

    repo.save_all([_make_disclosure("20260115000001")])
    loaded = repo.load_all()

    assert len(loaded) == 1
    assert loaded[0].rcept_no == "20260115000001"
    assert loaded[0].corp_name == "코미코"
    assert loaded[0].pre_split_common_shares == 1000


def test_save_all_upserts_by_rcept_no_instead_of_duplicating(tmp_path):
    db_path = tmp_path / "stock_splits.db"
    repo = SqliteStockSplitRepositoryAdapter(db_path=str(db_path))

    repo.save_all([_make_disclosure("20260115000001", corp_name="코미코")])
    updated = _make_disclosure("20260115000001", corp_name="코미코(정정)")
    repo.save_all([updated])

    loaded = repo.load_all()

    assert len(loaded) == 1
    assert loaded[0].corp_name == "코미코(정정)"


def test_load_all_returns_empty_list_when_db_file_missing(tmp_path):
    db_path = tmp_path / "does_not_exist.db"
    repo = SqliteStockSplitRepositoryAdapter(db_path=str(db_path))

    assert repo.load_all() == []


def test_save_all_creates_disclosures_table_with_rcept_no_primary_key(tmp_path):
    db_path = tmp_path / "stock_splits.db"
    repo = SqliteStockSplitRepositoryAdapter(db_path=str(db_path))

    repo.save_all([_make_disclosure("20260115000001")])

    con = sqlite3.connect(str(db_path))
    try:
        cols = con.execute("PRAGMA table_info(disclosures)").fetchall()
        pk_cols = [c[1] for c in cols if c[5] == 1]
        assert pk_cols == ["rcept_no"]
    finally:
        con.close()

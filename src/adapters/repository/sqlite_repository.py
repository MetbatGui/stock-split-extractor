import os
import sqlite3
from typing import List
from domain.models import StockSplitDisclosure
from ports.repository import StockSplitReaderPort, StockSplitWriterPort

_SCHEMA = """
CREATE TABLE IF NOT EXISTS disclosures (
    rcept_no TEXT PRIMARY KEY,
    corp_name TEXT,
    report_nm TEXT,
    presenter TEXT,
    reg_date TEXT,
    is_cancelled INTEGER,
    parent_rcept_no TEXT,
    original_reg_date TEXT,
    pre_split_common_shares INTEGER,
    post_split_common_shares INTEGER,
    new_share_listing_date TEXT,
    board_resolution_date TEXT
)
"""

_UPSERT = """
INSERT INTO disclosures (
    rcept_no, corp_name, report_nm, presenter, reg_date, is_cancelled,
    parent_rcept_no, original_reg_date, pre_split_common_shares,
    post_split_common_shares, new_share_listing_date, board_resolution_date
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(rcept_no) DO UPDATE SET
    corp_name=excluded.corp_name,
    report_nm=excluded.report_nm,
    presenter=excluded.presenter,
    reg_date=excluded.reg_date,
    is_cancelled=excluded.is_cancelled,
    parent_rcept_no=excluded.parent_rcept_no,
    original_reg_date=excluded.original_reg_date,
    pre_split_common_shares=excluded.pre_split_common_shares,
    post_split_common_shares=excluded.post_split_common_shares,
    new_share_listing_date=excluded.new_share_listing_date,
    board_resolution_date=excluded.board_resolution_date
"""


class SqliteStockSplitRepositoryAdapter(StockSplitReaderPort, StockSplitWriterPort):
    """
    수집 완료된 도메인 모델 데이터를 로컬 SQLite DB 파일에 영속화하는 어댑터
    (Reader 및 Writer 구현체). rcept_no(접수번호)를 PK로 삼아 SQL upsert로 저장한다.
    """

    def __init__(self, db_path: str = "data/stock_splits.db") -> None:
        self.db_path = db_path
        dir_name = os.path.dirname(self.db_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.execute(_SCHEMA)
        return con

    def save_all(self, disclosures: List[StockSplitDisclosure]) -> None:
        """전체 목록을 하나의 트랜잭션으로 upsert한다. 실패 시 rollback한다."""
        con = self._connect()
        try:
            con.execute("BEGIN")
            for disc in disclosures:
                con.execute(
                    _UPSERT,
                    (
                        disc.rcept_no,
                        disc.corp_name,
                        disc.report_nm,
                        disc.presenter,
                        disc.reg_date,
                        int(disc.is_cancelled),
                        disc.parent_rcept_no,
                        disc.original_reg_date,
                        disc.pre_split_common_shares,
                        disc.post_split_common_shares,
                        disc.new_share_listing_date,
                        disc.board_resolution_date,
                    ),
                )
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def load_all(self) -> List[StockSplitDisclosure]:
        """DB에 저장된 전체 공시를 도메인 모델 리스트로 역직렬화한다."""
        if not os.path.exists(self.db_path):
            return []

        con = self._connect()
        try:
            rows = con.execute(
                """
                SELECT rcept_no, corp_name, report_nm, presenter, reg_date, is_cancelled,
                       parent_rcept_no, original_reg_date, pre_split_common_shares,
                       post_split_common_shares, new_share_listing_date, board_resolution_date
                FROM disclosures
                """
            ).fetchall()
        finally:
            con.close()

        return [
            StockSplitDisclosure(
                rcept_no=row[0],
                corp_name=row[1],
                report_nm=row[2],
                presenter=row[3],
                reg_date=row[4],
                is_cancelled=bool(row[5]),
                parent_rcept_no=row[6],
                original_reg_date=row[7],
                pre_split_common_shares=row[8],
                post_split_common_shares=row[9],
                new_share_listing_date=row[10],
                board_resolution_date=row[11],
            )
            for row in rows
        ]

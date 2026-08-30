import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from adapters.repository.google_drive_repository import GoogleDriveStockSplitRepositoryAdapter


def _adapter_with_fake_service(fake_service):
    adapter = GoogleDriveStockSplitRepositoryAdapter(folder_id="fake-folder-id")
    adapter._service = fake_service
    return adapter


def test_sync_down_if_newer_treats_no_remote_file_as_normal():
    """원격에 파일이 없으면(query 성공, 빈 결과) 예외 없이 False를 반환해야 한다."""
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = {"files": []}
    adapter = _adapter_with_fake_service(fake_service)

    result = adapter.sync_down_if_newer("stock_splits.db", "data/stock_splits.db")

    assert result is False


def test_sync_down_if_newer_propagates_metadata_query_failure_instead_of_swallowing():
    """메타데이터 조회 자체가 실패하면(인증 오류 등) "없음"으로 오인하지 말고 예외를
    그대로 전파해야 한다 - db_ssot_guide.md §6.1. 호출부(service.py)가 이 예외를 잡아
    "로컬로 계속 진행"을 로그로 명확히 남긴다."""
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.side_effect = RuntimeError("auth failed")
    adapter = _adapter_with_fake_service(fake_service)

    try:
        adapter.sync_down_if_newer("stock_splits.db", "data/stock_splits.db")
        assert False, "예외가 전파돼야 한다"
    except RuntimeError:
        pass

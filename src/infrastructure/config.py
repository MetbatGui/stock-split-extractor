import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

# .env 환경 변수 로드
load_dotenv()

class AppConfig(BaseModel):
    """주식분할 수집기 애플리케이션 전역 설정 클래스.

    환경 변수와 하드코딩된 기본 경로를 중앙에서 관리합니다.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # 기본 디렉토리 경로
    data_dir: Path = Path("data")
    secrets_dir: Path = Path("secrets")
    cache_dir: Path = Path("cache")

    # 상세 파일 경로
    json_file_path: Path = Path("data/stock_splits_with_history.json")
    excel_file_path: Path = Path("data/stock_splits_with_history.xlsx")
    client_secret_path: Path = Path("secrets/client_secret.json")
    token_path: Path = Path("secrets/token.json")

    # 구글 드라이브 동기화 폴더 ID (.env에서 로딩)
    google_stock_split_folder_id: str = os.getenv("GOOGLE_STOCK_SPLIT_FOLDER_ID") or os.getenv("GOOGLE_DRIVE_FOLDER_ID") or ""

    @classmethod
    def load(cls) -> "AppConfig":
        """설정 인스턴스를 반환합니다."""
        return cls()

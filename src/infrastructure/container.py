import logging
from typing import Optional

from infrastructure.config import AppConfig
from adapters.scraper.dart_web_scraper import DartWebScraperAdapter
from adapters.parser.opendart_xml_parser import OpenDartXmlParserAdapter
from adapters.repository.local_json_repository import LocalJsonStockSplitRepositoryAdapter
from adapters.repository.local_excel_repository import LocalExcelStockSplitRepositoryAdapter
from adapters.repository.google_drive_repository import GoogleDriveStockSplitRepositoryAdapter
from adapters.repository.composite_repository import CompositeStockSplitWriterAdapter
from application.service import StockSplitCollectionService

logger = logging.getLogger(__name__)

class Container:
    """애플리케이션 전역 의존성을 조립하고 관리하는 DI 컨테이너."""

    def __init__(self) -> None:
        # 1. 설정 로드
        self._config = AppConfig.load()

        # 2. 로컬 필수 디렉토리 자동 생성 보장
        self._config.data_dir.mkdir(parents=True, exist_ok=True)
        self._config.secrets_dir.mkdir(parents=True, exist_ok=True)
        self._config.cache_dir.mkdir(parents=True, exist_ok=True)

        # 3. 인프라 어댑터 싱글톤 구성
        self._scraper_adapter = DartWebScraperAdapter()
        self._parser_adapter = OpenDartXmlParserAdapter(cache_dir=str(self._config.cache_dir))
        self._local_json_repository = LocalJsonStockSplitRepositoryAdapter(
            file_path=str(self._config.json_file_path)
        )
        self._local_excel_repository = LocalExcelStockSplitRepositoryAdapter(
            file_path=str(self._config.excel_file_path)
        )

        # 4. 조건부 구글 드라이브 리포지토리 구성
        self._gdrive_repository: Optional[GoogleDriveStockSplitRepositoryAdapter] = None
        self._init_gdrive_repository()

        # 5. Composite Writer 구성 (다중 영속화 캡슐화)
        writers = [self._local_json_repository, self._local_excel_repository]
        if self._gdrive_repository:
            writers.append(self._gdrive_repository)
        self._composite_writer = CompositeStockSplitWriterAdapter(writers=writers)

        # 6. 비즈니스 서비스 구성 (의존성 결합)
        self._collection_service = StockSplitCollectionService(
            scraper_port=self._scraper_adapter,
            parser_port=self._parser_adapter,
            reader_port=self._local_json_repository,
            writer_port=self._composite_writer,
            sync_port=self._gdrive_repository
        )

    def _init_gdrive_repository(self) -> None:
        """구글 드라이브 폴더 설정 및 자격 증명 파일 체크 후 어댑터를 초기화합니다."""
        if not self._config.google_stock_split_folder_id:
            logger.warning("[Container] GOOGLE_STOCK_SPLIT_FOLDER_ID 환경변수가 정의되지 않아 클라우드 동기화를 구성하지 않습니다.")
            return

        if not self._config.client_secret_path.exists():
            logger.warning(
                f"[Container] 구글 드라이브 자격 증명 파일('{self._config.client_secret_path}')이 존재하지 않아 "
                "클라우드 동기화를 구성하지 않습니다."
            )
            return

        try:
            self._gdrive_repository = GoogleDriveStockSplitRepositoryAdapter(
                folder_id=self._config.google_stock_split_folder_id,
                file_name=self._config.json_file_path.name,
                credentials_path=str(self._config.client_secret_path),
                token_path=str(self._config.token_path)
            )
        except Exception as e:
            logger.error(f"[Container] 구글 드라이브 어댑터 초기화 실패 (로컬 수집 모드로 작동): {e}")

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def collection_service(self) -> StockSplitCollectionService:
        return self._collection_service

# 전역 컨테이너 싱글톤 인스턴스 생성
container = Container()

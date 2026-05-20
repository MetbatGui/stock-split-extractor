import os
import json
import logging
import tempfile
from typing import List, Optional, Any
from google.oauth2.credentials import Credentials  # type: ignore
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
from google.auth.transport.requests import Request  # type: ignore
import io
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload  # type: ignore


from domain.models import StockSplitDisclosure
from ports.repository import StockSplitRepositoryPort

class GoogleDriveStockSplitRepositoryAdapter(StockSplitRepositoryPort):
    """
    수집 완료된 도메인 모델 데이터를 구글 드라이브 (SSOT)에 
    JSON 파일 형태로 저장하고 동기화 업로드하는 어댑터 (StockSplitRepositoryPort 구현체)
    """
    
    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(
        self,
        folder_id: str,
        file_name: str = "stock_splits_1year.json",
        credentials_path: str = "secrets/client_secret.json",
        token_path: str = "secrets/token.json"
    ) -> None:
        """
        구글 드라이브 리포지토리 어댑터 초기화
        
        Args:
            folder_id: 구글 드라이브 대상 폴더 ID
            file_name: 저장할 클라우드 파일 이름
            credentials_path: OAuth2 클라이언트 보안 비밀번호 파일 경로
            token_path: 토큰 캐시 저장 파일 경로
        """
        # 기본 로거 연동
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(self.__name__ if hasattr(self, '__name__') else "GoogleDriveRepoAdapter")
        
        self.folder_id = folder_id.strip()
        self.file_name = file_name
        self.credentials_path = credentials_path
        self.token_path = token_path
        
        # 구글 드라이브 API 서비스 지연 빌드 (lazy load)
        self._service: Optional[Any] = None

    @property
    def service(self) -> Any:
        """구글 드라이브 서비스 싱글톤 획득"""
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def _authenticate(self) -> Any:
        """구글 드라이브 OAuth2 인증 및 서비스 빌드"""
        creds = None
        
        # 1. 기존 토큰 파일 확인
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)
            except Exception as e:
                self.logger.warning(f"Failed to load cached token: {e}")
        
        # 2. 토큰이 유효하지 않으면 새로 생성하거나 갱신
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                self.logger.info("[GDriveRepo] Token expired. Refreshing token...")
                try:
                    creds.refresh(Request())
                except Exception as refresh_err:
                    self.logger.error(f"[GDriveRepo] Token refresh failed: {refresh_err}")
                    creds = None
            
            # 새로 인증 받기
            if not creds:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"OAuth2 credentials file not found at: {self.credentials_path}. "
                        "Please place client_secret.json inside 'secrets/' folder."
                    )
                
                self.logger.info("[GDriveRepo] Interactive authentication starting...")
                print("브라우저 창이 열리면 구글 로그인을 완료해 주세요.")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # 갱신된 토큰 저장
            secrets_dir = os.path.dirname(self.token_path)
            if secrets_dir:
                os.makedirs(secrets_dir, exist_ok=True)
            with open(self.token_path, 'w', encoding='utf-8') as token_file:
                token_file.write(creds.to_json())
            self.logger.info("[GDriveRepo] Google Drive API Authentication success!")

        return build('drive', 'v3', credentials=creds)

    def _find_file_by_name(self, file_name: str) -> Optional[str]:
        """지정한 폴더 내에 동일한 이름을 가진 파일의 ID를 조회합니다."""
        escaped_name = file_name.replace("'", "\\'")
        query = f"name='{escaped_name}' and '{self.folder_id}' in parents and trashed=false"
        
        try:
            results = self.service.files().list(
                q=query,
                fields="files(id, name)",
                pageSize=1
            ).execute()
            
            files = results.get('files', [])
            return files[0]['id'] if files else None
        except Exception as e:
            self.logger.warning(f"[GDriveRepo] Query error during file name search: {e}")
            return None

    def save_all(self, disclosures: List[StockSplitDisclosure]) -> None:
        """
        도메인 모델 리스트를 JSON 문자열로 직렬화하여 구글 드라이브에 안전하게 동기화 업로드합니다.
        메모리 버퍼(BytesIO)를 활용하여 윈도우 환경의 파일 락(WinError 32)을 원천 방지합니다.
        """
        if not self.folder_id:
            self.logger.warning("[GDriveRepo] GOOGLE_STOCK_SPLIT_FOLDER_ID is empty. Cloud sync skipped.")
            return

        # 1. 도메인 데이터를 메모리 상에서 JSON 구조로 변환
        data_to_save = [disc.model_dump() for disc in disclosures]
        json_content = json.dumps(data_to_save, ensure_ascii=False, indent=4)
        
        # 2. BytesIO 메모리 버퍼 생성
        json_bytes = json_content.encode('utf-8')
        fh = io.BytesIO(json_bytes)

        try:
            # 3. 구글 드라이브 상에서 파일명 조회 및 덮어쓰기 여부 결정
            existing_file_id = self._find_file_by_name(self.file_name)
            
            # 메모리 버퍼용 MediaIoBaseUpload 설정
            media = MediaIoBaseUpload(
                fh,
                mimetype='application/json',
                resumable=True
            )
            
            if existing_file_id:
                # 3-A. 덮어쓰기 업데이트
                file = self.service.files().update(
                    fileId=existing_file_id,
                    media_body=media
                ).execute()
                self.logger.info(f"[GDriveRepo] Successfully UPDATED SSOT file on Google Drive (ID: {file.get('id')})")
            else:
                # 3-B. 신규 파일 업로드
                file_metadata = {
                    'name': self.file_name,
                    'parents': [self.folder_id]
                }
                file = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, webViewLink'
                ).execute()
                self.logger.info(f"[GDriveRepo] Successfully UPLOADED new SSOT file to Google Drive (ID: {file.get('id')})")
                
        except Exception as upload_err:
            self.logger.error(f"[GDriveRepo] Error uploading file to Google Drive: {upload_err}")
            raise upload_err


    def upload_local_file(self, local_path: str, remote_name: str, mime_type: str) -> None:
        """
        로컬에 존재하는 임의의 파일(예: 엑셀, JSON 등)을 구글 드라이브의 대상 폴더에 업로드합니다.
        기존 동일한 이름의 파일이 있으면 자동으로 찾아 덮어씁니다.
        """
        if not self.folder_id:
            self.logger.warning("[GDriveRepo] GOOGLE_STOCK_SPLIT_FOLDER_ID is empty. Upload skipped.")
            return

        if not os.path.exists(local_path):
            self.logger.error(f"[GDriveRepo] Local file not found for upload: {local_path}")
            return

        try:
            # 기존 구글 드라이브상 파일 조회
            existing_file_id = self._find_file_by_name(remote_name)
            media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)

            if existing_file_id:
                # 덮어쓰기 업데이트
                file = self.service.files().update(
                    fileId=existing_file_id,
                    media_body=media
                ).execute()
                self.logger.info(f"[GDriveRepo] Successfully UPDATED local file '{remote_name}' to Google Drive (ID: {file.get('id')})")
            else:
                # 신규 생성 업로드
                file_metadata = {
                    'name': remote_name,
                    'parents': [self.folder_id]
                }
                file = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()
                self.logger.info(f"[GDriveRepo] Successfully UPLOADED new local file '{remote_name}' to Google Drive (ID: {file.get('id')})")
        except Exception as e:
            self.logger.error(f"[GDriveRepo] Failed to upload local file '{remote_name}': {e}")
            raise e


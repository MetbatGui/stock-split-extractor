# 📈 Stock Split Extractor

DART(전자공시시스템)에서 국내 상장사의 **주식분할결정** 공시를 자동으로 수집·정리해,
회사별/연도별 엑셀 리포트를 만들고 구글 드라이브에 업로드하는 배치 프로그램입니다.
기재정정·철회 이력까지 역추적해 최초 공시일과 부모-자식 관계를 복원합니다.

이 문서는 다음 개발자 또는 시스템 관리자가 프로젝트를 빠르고 정확하게 파악하고 인수인계받을
수 있도록 작성되었습니다.

---

## ✨ 주요 기능

- **DART 공시 자동 수집**: 지정 기간의 주식분할결정 공시 목록을 스크래핑합니다.
- **정정/철회 이력 복원**: 기재정정·철회 공시는 DART 뷰어의 이력 목록을 역추적해, 누락된 이전
  공시(최초 공시 포함)를 자동으로 복원 적재하고 부모-자식 접수번호 관계를 계산합니다.
- **완료 판정 (재수집 스킵)**: 이미 SQLite DB에 저장된 접수번호(`rcept_no`)는
  `--refresh`를 주지 않는 한 XML 본문을 다시 다운로드·파싱하지 않습니다.
- **연도별 엑셀 리포트**: 프리미엄 스타일(자동 열 너비 등)이 적용된 `액면분할(YYYY년).xlsx`를
  연도별로 생성합니다.
- **구글 드라이브 동기화**: SQLite DB(SSOT)와 연도별 엑셀 파일을 구글 드라이브에 자동 업로드합니다.

---

## 🏗 아키텍처

포트-어댑터(Hexagonal Architecture) 구조로, 비즈니스 로직이 외부 인프라(DART, SQLite, 구글
드라이브)에 직접 의존하지 않습니다.

```
stock-split-extractor/
├── docker/              # Docker 환경 구축 파일 (Dockerfile, docker-compose, cron 스크립트)
├── secrets/             # 인증 자격 증명 키 저장소 (Git 제외 대상)
│   ├── client_secret.json     # Google OAuth 클라이언트 보안 비밀
│   └── token.json              # 최초 실행 시 생성되는 OAuth 토큰
├── data/                # SQLite SSOT DB(stock_splits.db) 및 연도별 엑셀 산출물 (Git 제외 대상)
├── src/
│   ├── domain/          # 순수 도메인 모델 (StockSplitDisclosure, 정정 체인 Aggregate, CollectionRunResult)
│   ├── ports/            # 어댑터용 인터페이스 (scraper, parser, repository)
│   ├── application/      # StockSplitCollectionService - 수집→완료판정→파싱→저장→업로드 오케스트레이션
│   └── adapters/
│       ├── scraper/      # DART 목록 스크래퍼
│       ├── parser/       # OpenDART XML 상세 파서
│       └── repository/   # SQLite(SSOT), Excel(산출물), Google Drive(CloudSync), Composite Writer
├── tests/               # 단위 테스트
├── main.py               # CLI 진입점
└── pyproject.toml
```

- `StockSplitCollectionService`가 GDrive에서 DB를 받아오는 것부터 결과 업로드까지 전체 흐름을
  오케스트레이션합니다.
- `SqliteStockSplitRepositoryAdapter`가 SSOT이며, `rcept_no`(접수번호 — 기재정정이 나면 항상 새
  번호가 붙는 정정 불가능한 식별자)를 PK로 SQL upsert(`INSERT ... ON CONFLICT DO UPDATE`)합니다.
  Excel/구글 드라이브는 이 DB의 파생 산출물일 뿐입니다.
- `CompositeStockSplitWriterAdapter`가 SQLite·Excel 두 writer를 한 번의 `save_all()` 호출로 묶습니다.
- `GoogleDriveStockSplitRepositoryAdapter`는 파일 왕복(`sync_down_if_newer`/`sync_up_file`)만
  담당하는 `CloudSyncPort` 구현체입니다 — DB 내용 자체를 알지 못합니다.

---

## 🚀 환경 설정 및 설치

### 1. 사전 요구 사항
- **Python 3.14** 이상 및 **`uv`** 패키지 관리자
- DART Open API 인증키
- **Docker 및 Docker Compose** (컨테이너 실행 시)

### 2. 패키지 설치
```bash
uv sync
```

### 3. 환경 변수 설정 (`.env`)
```env
DART_API_KEY=your_dart_open_api_key
GOOGLE_STOCK_SPLIT_FOLDER_ID=your_google_drive_folder_id
```

### 4. 시크릿 설정
`secrets/client_secret.json`(Google Cloud Console에서 발급받은 OAuth 2.0 Desktop app 클라이언트)을
넣어두면, `main.py` 최초 실행 시 브라우저 인증을 거쳐 `secrets/token.json`이 자동 생성됩니다.

---

## 💻 사용법

```bash
# 최근 N일 수집 (기본 7일) - 이미 저장된 접수번호는 재파싱하지 않음
python main.py --days 7

# 특정 기간 수집
python main.py --start 20260101 --end 20260201

# 기존 상태를 무시하고 강제 재수집(재파싱)
python main.py --start 20260101 --end 20260201 --refresh
```

---

## 🐳 Docker로 실행

```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml run --rm extractor python main.py --days 7
docker compose -f docker/docker-compose.yml up -d extractor-cron
```

컨테이너 내장 cron이 스케줄에 따라 `--days 7` 수집을 자동 실행합니다. 스케줄은
`docker/crontab`을 참고하세요(기본: 평일 18:00 KST — 공시 데이터라 장마감 시각과 무관하게
잡혀 있으니 필요에 맞게 조정 가능).

---

## 🧪 테스트

```bash
uv run pytest
```

---

## 💡 인수인계 시 주의 사항 (개발 팁)

1. **SQLite가 SSOT, `data/`는 작업 사본일 뿐**: 매 실행 시작 시 구글 드라이브에서
   `stock_splits.db`를 받아와 로컬 `data/`에 작업 사본을 두고, 종료 시 다시 업로드합니다.
   `data/`가 지워져도 GDrive에서 그대로 복구됩니다. 반대로 로컬 `data/`의 DB를 직접 손으로
   고치지 마세요 — 다음 실행에서 원격이 다시 덮어씁니다.
2. **완료 판정된(스킵된) 공시를 정정 체인 재해석에 다시 태우지 말 것**: `rcept_no`가 이미 DB에
   있으면 파싱은 건너뛰지만, 그 객체를 `StockSplitDisclosureChain.resolve_original_dates()`에
   다시 넣으면 이번 실행의 `relation_map`에 안 잡히는 순간(정정 이력 스크래핑이 이번엔
   실패했거나 대상 밖인 경우) 이미 올바르게 계산해둔 `original_reg_date`가 자기 자신 날짜로
   조용히 덮어써집니다. `tests/unit/test_service_skip_existing.py`의 회귀 테스트가 이 케이스를
   고정해뒀습니다.
3. **`rcept_no`가 유일하게 신뢰 가능한 PK**: DART 기재정정 공시는 항상 새 접수번호를 받으므로
   PK로 안전합니다. 다른 필드(회사명, 등록일 등)는 정정으로 바뀔 수 있어 PK에 넣지 않습니다.
4. **DART 공시 목록/이력 스크래핑은 웹 스크래핑**(`DartWebScraperAdapter`)**, 본문 상세는
   OpenDART API**(`OpenDartXmlParserAdapter`, `DART_API_KEY` 필요)로 이원화돼 있습니다. 목록
   스크래핑이 막히면 이력 복원(정정 체인)이 부실해질 수 있으니, 429/차단 응답이 잦아지면 딜레이
   조정을 먼저 고려하세요.
5. **의존성 패키지 관리 (`uv`)**: `pip install` 대신 `uv add <패키지명>`을 사용해
   `pyproject.toml`/`uv.lock`을 자동 최신화하세요.

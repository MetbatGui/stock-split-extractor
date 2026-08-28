# Stock Split Extractor

DART(전자공시시스템)에서 국내 상장사의 **주식분할결정** 공시를 자동으로 수집·정리해,
회사별/연도별 엑셀 리포트를 만들고 구글 드라이브에 업로드하는 배치 프로그램입니다.
기재정정/철회 이력까지 추적해 최초 공시일과 부모-자식 관계를 복원합니다.

## 무엇을 하는가

1. 지정된 기간의 DART 주식분할결정 공시 목록을 스크래핑
2. 기재정정·철회 공시는 DART 뷰어의 이력 목록을 역추적해 누락된 이전 공시(최초 공시 포함)를
   복원 적재
3. 이미 SQLite DB에 저장된 접수번호(rcept_no)는 재파싱하지 않고 건너뛰어(완료 판정),
   신규/미확인 공시만 XML 본문을 다운로드·파싱
4. 정정 체인 내 최초 원본 공시일과 부모-자식 접수번호 관계를 계산
5. 결과를 SQLite DB(SSOT)에 upsert하고, 연도별 `액면분할(YYYY년).xlsx`로 렌더링
6. DB와 엑셀 파일을 구글 드라이브에 업로드

## 아키텍처

포트-어댑터(Hexagonal) 구조로, 비즈니스 로직이 외부 인프라(DART, SQLite, 구글 드라이브)에
직접 의존하지 않습니다.

```
src/
├── domain/     # 순수 도메인 모델 (StockSplitDisclosure, 정정 체인 Aggregate, 실행 결과 값 객체)
├── ports/      # 어댑터용 인터페이스 (scraper, parser, repository)
├── application/ # 서비스 오케스트레이션 (수집→완료판정→파싱→저장→업로드)
└── infra/adapters, infrastructure/
    ├── scraper/    # DART 목록 스크래퍼
    ├── parser/     # OpenDART XML 상세 파서
    └── repository/ # SQLite(SSOT), Excel(산출물), Google Drive(CloudSync), Composite Writer
```

- `StockSplitCollectionService`가 수집부터 업로드까지 전체 흐름을 오케스트레이션합니다.
- `SqliteStockSplitRepositoryAdapter`가 SSOT이며, `rcept_no`(접수번호, 정정 불가능한 식별자)를
  PK로 SQL upsert합니다. Excel/구글 드라이브는 그 결과물일 뿐입니다.
- `CompositeStockSplitWriterAdapter`가 SQLite·Excel 두 writer를 한 번의 `save_all()` 호출로 묶습니다.

## 요구 사항

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (의존성 관리)
- DART Open API 인증키
- 구글 드라이브 API OAuth 클라이언트(`secrets/client_secret.json`)

## 설치 및 설정

```bash
uv sync
```

`.env` 파일에 다음 값을 설정합니다.

```
DART_API_KEY=...
GOOGLE_STOCK_SPLIT_FOLDER_ID=...
```

`secrets/client_secret.json`(구글 OAuth 클라이언트)이 있어야 하며, `main.py` 최초 실행 시
브라우저 인증을 거치면 `secrets/token.json`이 생성됩니다.

## 사용법

```bash
# 최근 N일 수집 (기본 7일)
python main.py --days 7

# 특정 기간 수집
python main.py --start 20260101 --end 20260201

# 기존 상태를 무시하고 강제 재수집(재파싱)
python main.py --start 20260101 --end 20260201 --refresh
```

## Docker로 실행

```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml run --rm extractor python main.py --days 7
docker compose -f docker/docker-compose.yml up -d extractor-cron
```

컨테이너 내장 cron이 스케줄에 따라 `--days 7` 수집을 주기 실행합니다. 스케줄은
`docker/crontab`을 참고하세요(기본: 평일 18:00 KST).

## 테스트

```bash
uv run pytest
```

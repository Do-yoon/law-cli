# law-cli — 대한민국 법령 조문 조회 CLI

법령명과 조번호를 입력하면 해당 조문을 **출처(일차자료) URL과 함께** 보여주는 명령줄 도구입니다.
법률 지식이나 Git 지식이 없어도 "일차자료를 정확히 읽는" 첫걸음이 되도록 만들었습니다.

조문 위치를 모를 때는 **하이브리드 검색**(`--semantic`)으로 자연어 질의를 할 수 있습니다 —
Hugging Face 임베딩 모델(기본 [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3))의 의미 검색과
[Kiwi](https://github.com/bab2min/kiwipiepy) 형태소 분석 기반 tsvector 어휘 검색을
PostgreSQL([pgvector](https://github.com/pgvector/pgvector)) 위에서 RRF로 융합합니다.

데이터는 [legalize-kr](https://github.com/legalize-kr/legalize-kr) 아카이브(국가법령정보센터 공공데이터 기반)를 사용합니다.

## 설치

Python 3.10 이상이 필요합니다.

```bash
# 1) 법령 아카이브 준비 (홈 디렉토리 권장)
git clone https://github.com/legalize-kr/legalize-kr.git ~/legalize-kr

# 2) law-cli 설치
git clone https://github.com/Do-yoon/law-cli.git
cd law-cli
pip install .        # 또는: uv tool install .
```

## 사용법

```bash
# 민법 제839조의2 조회
law-cli 민법 839의2

# 스토킹처벌법 제18조 — 2023년 개정 "이전" 시점의 조문 조회
law-cli 스토킹범죄의처벌등에관한법률 18 --as-of 2023-06-30

# 조문 목차 보기
law-cli 민법 --toc

# 법령명을 모를 때: 키워드로 검색
law-cli --search 스토킹

# 시행령·시행규칙 조회
law-cli 민법 --type 시행령 --toc

# 자연어 의미 검색 — 조문 위치를 모를 때 (아래 "의미 검색" 참고)
law-cli --semantic "이혼할 때 재산을 나누는 규정" --law-filter 민법
```

### `--as-of` — 그 날짜 당시의 조문

법령은 계속 개정됩니다. "지금의 조문"과 "그 일이 있었던 당시의 조문"은 다를 수 있습니다.
`--as-of 날짜`를 붙이면 해당 날짜 당시에 공포되어 있던 버전의 조문을 보여줍니다.

### 출력 예

```
============================================================
스토킹범죄의 처벌 등에 관한 법률 — 법률
  공포 2021-04-20 / 시행 2021-10-21 / 시행
  ※ 2023-06-30 당시 버전 (commit d23de3f97821)
============================================================

##### 제18조 (스토킹범죄)

...조문 내용...

------------------------------------------------------------
출처(일차자료): https://www.law.go.kr/법령/스토킹범죄의처벌등에관한법률
이 출력은 참고용 조회 결과입니다. 반드시 위 출처의 원문으로 확인하세요.
```

## 하이브리드 검색 (`--semantic`)

조문을 조 단위로 청킹해 두 갈래로 색인합니다:

1. **의미 경로(주)** — 임베딩 모델로 조문 원문을 벡터화 (pgvector, cosine).
   일상어 질의와 조문 언어의 어휘 간극을 의미로 메웁니다.
2. **어휘 경로(보조)** — Kiwi 형태소 분석으로 내용어만 추출해 tsvector로 색인.
   조문에 그대로 나오는 단어("과태료", "접근")의 정확 일치를 보장합니다.

질의도 같은 두 경로로 검색한 뒤 **RRF(Reciprocal Rank Fusion)** 로 순위를
융합해 top-k를 출력합니다. 결과에는 경로별 순위(의미 n위 · 어휘 m위)가 표시됩니다.

### 준비

```bash
# 1) 추가 의존성 설치
uv sync --extra semantic          # 개발 중
uv tool install "law-cli[semantic]"   # 도구로 설치하는 경우

# 2) PostgreSQL + pgvector (macOS 예시)
brew install postgresql@17 pgvector
brew services start postgresql@17
# 데이터베이스(기본: law_cli)는 첫 실행 시 자동 생성됩니다
```

### 사용

```bash
# 법령명을 좁혀서 검색 (권장 — 처음 한 번만 임베딩하고 이후엔 재사용)
law-cli --semantic "이혼할 때 재산을 나누는 규정" --law-filter 민법

# 다른 Hugging Face 임베딩 모델 사용
law-cli --semantic "질의문" --model intfloat/multilingual-e5-large --law-filter 민법

# 결과 개수·법령 종류 지정
law-cli --semantic "질의문" --law-filter 민법 --top-k 10 --type 시행령

# 아카이브 전체 색인 (3천여 법령 — 오래 걸림, 명시적 동의 필요)
law-cli --semantic "질의문" --index-all
```

- 임베딩은 (모델, 법령, 파일 해시) 기준으로 **증분 동기화**됩니다 —
  아카이브를 `git pull`로 갱신하면 바뀐 법령만 다시 임베딩합니다.
- 검색 결과에는 유사도·미리보기·출처 URL과 함께, 원문을 정확히 볼 수 있는
  결정적 조회 명령(`law-cli 법령명 조번호`)이 안내됩니다.
- 데이터베이스명은 `--db` 옵션 또는 환경변수 `LAW_CLI_DB`로 바꿀 수 있습니다.
- 벡터스토어는 아카이브의 파생물입니다 — 언제든 `DROP DATABASE` 후 재생성해도 됩니다.

## 저장소 위치 지정

`legalize-kr` 아카이브는 다음 순서로 자동 탐지합니다:

1. `--repo <경로>` 옵션
2. 환경변수 `LEGALIZE_KR_REPO`
3. `./legalize-kr` → `~/legalize-kr`

## 주의사항

- 이 도구는 **법률 자문이 아닙니다.** 출력은 참고용이며, 반드시 출처의 원문으로 확인하세요.
- 아카이브는 공공데이터 API에서 생성되며, 공포 시점과 아카이브 반영 시점 사이에 시차가 있을 수 있습니다.

## 개발

```bash
uv sync
uv run pytest
```

## 라이선스

MIT

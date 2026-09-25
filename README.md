**한국어** | [English](README.en.md)

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

# 주제별 프리셋으로 좁히기 (가족·노동·주거·교통·형사·소비자·금전·개인정보)
law-cli --semantic "월급을 못 받았어요" --preset 노동

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
- `--preset`은 주제별 법령 묶음(가족·노동·주거·교통·형사·소비자·금전·개인정보)으로
  범위를 좁힙니다.
  키워드 부분일치(`--law-filter`)와 달리 엄선된 법령명과 정확히 일치할 때만
  포함하므로, "민법" 키워드가 "난민법"까지 잡는 식의 오염이 없습니다.
  (`--law-filter`와 동시에 쓸 수 없습니다.)
- 데이터베이스명은 `--db` 옵션 또는 환경변수 `LAW_CLI_DB`로 바꿀 수 있습니다.
- 벡터스토어는 아카이브의 파생물입니다 — 언제든 `DROP DATABASE` 후 재생성해도 됩니다.
- 판례(判例) 코퍼스 확장은 보류 상태입니다 — 판례는 일차자료 아카이브(legalize-kr)의
  범위 밖이라, 별도의 데이터 소스와 라이선스 검토가 선행되어야 합니다.

## MCP 서버 — LLM 연동

일반인의 일상어를 법조문 언어로 해석하는 일은 LLM이 가장 잘합니다. law-cli는
그 반대편을 맡습니다 — LLM에게 **정확한 조문 전문과 일차자료 출처 URL**을 제공하는
MCP(Model Context Protocol) 서버 `law-cli-mcp`를 내장하고 있습니다. LLM이 사용자의
표현을 해석해 검색·조회 도구를 호출하고, 인용은 항상 원문과 출처에 근거하게 됩니다.

### 설치·등록

```bash
# MCP 서버 + 의미 검색 (semantic 없이 조회 도구만 쓰려면 "law-cli[mcp]")
uv tool install "law-cli[mcp,semantic]"

# Claude Code에 등록
claude mcp add law-kr -- law-cli-mcp
```

### GUI로 사용하기 — Claude Desktop

터미널 없이 쓰고 싶다면 [Claude Desktop](https://claude.ai/download)에 등록하세요.
채팅 화면이 곧 GUI가 됩니다 — 일상어로 질문하면 Claude가 알아서 조문을 찾아
출처와 함께 보여줍니다.

1. **설치** (최초 1회만 터미널 사용):
   ```bash
   git clone https://github.com/legalize-kr/legalize-kr.git ~/legalize-kr
   uv tool install "law-cli[mcp,semantic]"
   ```
2. **등록**: Claude Desktop → 설정 → 개발자 → **설정 편집**으로 열리는
   `claude_desktop_config.json`에 추가:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

   ```json
   {
     "mcpServers": {
       "law-kr": {
         "command": "law-cli-mcp",
         "env": { "LEGALIZE_KR_REPO": "/Users/나/legalize-kr" }
       }
     }
   }
   ```
3. **재시작 후 확인**: 채팅 입력창의 도구 아이콘에 `law-kr`이 보이면 성공입니다.
4. **사용**: 그냥 물어보세요 —
   > "전세 보증금을 못 돌려받고 있어. 관련 법 조항 찾아줘"
   > "2023년 6월 당시 스토킹처벌법 18조 내용이 뭐였어?"

PostgreSQL이 없어도 조회 도구(조문·목차·법령명 검색)는 동작합니다 —
자연어 검색(`semantic_search`)만 위 "준비"의 PostgreSQL + pgvector가 필요하며,
없으면 Claude가 키워드 검색으로 대신 찾아줍니다.

아카이브 위치는 환경변수 `LEGALIZE_KR_REPO`로 지정합니다 (미지정 시 관례 경로 탐지).

### 제공 도구

| 도구 | 역할 |
|------|------|
| `lookup_article` | 법령명 + 조번호로 조문 전문 조회 (`as_of` 시점 지정 지원) |
| `list_law_articles` | 법령의 조문 목차 |
| `search_laws` | 키워드로 법령명 검색 |
| `semantic_search` | 자연어 하이브리드 검색 (preset/law_filter로 범위 지정) |

`semantic_search`에는 PostgreSQL + pgvector가 필요합니다 (위 "준비" 참고).
모든 결과에는 출처 URL과 참고용 고지가 포함되며, 서버 instructions가 LLM에게
"인용 시 반드시 출처를 함께 제시할 것"을 지시합니다.

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

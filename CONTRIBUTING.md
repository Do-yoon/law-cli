# 기여 안내

law-cli에 관심을 가져주셔서 감사합니다. 버그 신고, 기능 제안, 문서 개선, 코드 기여
모두 환영합니다.

## 개발 환경

Python 3.10 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
git clone https://github.com/Do-yoon/law-cli.git
cd law-cli
uv sync                # 코어 + 테스트 의존성
uv run pytest          # 전체 테스트
```

조회 기능을 실제로 써보려면 법령 아카이브가 필요합니다:

```bash
git clone https://github.com/legalize-kr/legalize-kr.git ~/legalize-kr
uv run law-cli 민법 839의2
```

### 의미 검색(--semantic) 개발

의미 검색 로직의 단위 테스트는 가짜 임베더/스토어를 쓰므로 **추가 설치 없이 돌아갑니다.**
PostgreSQL 통합 테스트까지 로컬에서 실행하려면:

```bash
# PostgreSQL + pgvector (macOS 예시)
brew install postgresql@17 pgvector
brew services start postgresql@17

uv run --with "psycopg[binary]" pytest   # 통합 테스트 포함 (torch 불필요)
```

PostgreSQL이 없으면 통합 테스트는 자동 스킵되며, CI(pgvector 컨테이너)에서 검증됩니다.

## 원칙

코드를 바꿀 때 지켜야 할 이 프로젝트의 설계 원칙입니다 (자세한 배경은
`docs/law-cli-design-en.pptx` 참고):

1. **이중 경로** — 인용은 결정적 조회(파일·git), 탐색은 의미 검색. 역할을 섞지 않습니다.
2. **코어는 의존성 0** — 조회 기능은 표준 라이브러리만으로 동작해야 합니다.
   무거운 의존성은 `semantic` extra와 `law_cli/semantic.py` 안의 지연 임포트로 격리합니다.
3. **파생물 원칙** — 벡터스토어는 아카이브의 파생물입니다. 언제든 DROP 후 전량
   재생성 가능해야 합니다.
4. **법률 자문 아님** — 모든 출력에는 일차자료 URL과 참고용 고지가 동봉되어야 합니다.

## 스타일

- 주석·docstring·사용자 대상 메시지는 한국어로 씁니다.
- 커밋 메시지는 `type: 요약` 형식입니다 — `feat` / `fix` / `docs` / `test` /
  `refactor` / `chore` / `ci`. 예: `feat: --preset 법령 스코프 프리셋 추가`
- 기존 코드의 네이밍과 관례를 따릅니다.

## PR 절차

1. 저장소를 fork하고 `feature/...` 또는 `fix/...` 브랜치를 만듭니다.
2. 변경에는 테스트를 함께 추가합니다 (`tests/` — 가짜 스토어/임베더 패턴 참고).
3. `uv run pytest`가 통과하는지 확인하고 PR을 엽니다.
4. CI 통과와 리뷰 승인 후 squash merge됩니다.

법령 프리셋(`PRESETS`)에 법령을 추가하는 PR은, 해당 법령명이 legalize-kr 아카이브의
`kr/` 디렉토리명과 **정확히 일치**하는지 확인해 주세요 (부분일치가 아닌 동일 일치로
매칭됩니다).

## 버그 신고·기능 제안

[이슈](https://github.com/Do-yoon/law-cli/issues)로 남겨주세요. 템플릿이 준비되어
있습니다. 법령 데이터 자체의 오류(조문 누락·오탈자 등)는 이 저장소가 아니라
[legalize-kr](https://github.com/legalize-kr/legalize-kr) 쪽 이슈입니다.

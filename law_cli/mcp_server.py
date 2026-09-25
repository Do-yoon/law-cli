# MCP 서버 — LLM에게 법령 조회·검색 도구를 제공한다.
#
# 역할 분담: "일상어 → 법조문 언어" 해석은 LLM이 담당하고, law-cli는
# 정확한 조문 전문과 일차자료 출처 URL을 돌려준다. LLM은 사용자의 일상어
# 질의를 그대로 semantic_search에 넣어도 되고(임베딩이 어휘 간극을 메움),
# 법률용어로 재구성한 질의를 추가로 시도해 결과를 비교해도 된다.
#
# 주의: stdio MCP에서 stdout은 프로토콜 채널이다 — 이 모듈이 호출하는 경로는
# 화면 출력 없이 값을 반환하는 함수(semantic.search 등)만 사용하고, 진행
# 로그는 기존 코드대로 stderr로만 나간다.
from __future__ import annotations

import sys

from . import (
    _LAW_TYPES,
    PRESETS,
    extract_article,
    find_repo,
    list_articles,
    parse_article_number,
    parse_frontmatter,
    read_at,
    resolve_law_dir,
    suggest_laws,
)
from .semantic import DEFAULT_DB, DEFAULT_MODEL

_DISCLAIMER = "이 결과는 참고용입니다. 법률 자문이 아니며, 반드시 출처(source_url)의 원문으로 확인하세요."

_MISSING_MCP_MSG = (
    "MCP 서버에는 추가 의존성이 필요합니다. 다음으로 설치하세요:\n"
    '  uv tool install "law-cli[mcp,semantic]"'
)

# 의도된 도구 실패는 ToolError로 던져야 메시지가 LLM에게 그대로 전달된다
# (mcp 2.x는 일반 예외를 "Error executing tool ..."로 가린다)
try:
    from mcp.server.mcpserver.exceptions import ToolError  # mcp 2.x
except ImportError:
    try:
        from mcp.server.fastmcp.exceptions import ToolError  # mcp 1.x
    except ImportError:
        ToolError = RuntimeError  # mcp 미설치 환경 (도구 함수 단위 테스트용)

# Context 타입 주석이 있으면 FastMCP가 요청 컨텍스트를 주입한다 (progress 알림용)
try:
    from mcp.server.mcpserver import Context  # mcp 2.x
except ImportError:
    try:
        from mcp.server.fastmcp import Context  # mcp 1.x
    except ImportError:
        Context = None  # mcp 미설치 환경


def _fail(message: str):
    """도구 실패를 MCP 오류로 변환한다 — 메시지가 클라이언트(LLM)에 전달된다."""
    raise ToolError(message)


def _notify(ctx, coro_fn, *args):
    """워커 스레드에서 이벤트 루프의 async 알림 메서드를 호출한다.

    FastMCP는 sync 도구를 anyio 워커 스레드에서 돌리므로 from_thread로
    되돌아간다. 알림 실패(세션 없음·루프 밖 등)가 검색을 막으면 안 된다.
    """
    try:
        import anyio  # mcp 의존성 — mcp 미설치 환경에서는 알림만 건너뛴다

        anyio.from_thread.run(coro_fn, *args)
    except Exception:
        pass


def _law_file(law_name: str, law_type: str):
    """법령명·종류를 (repo, 파일 상대경로)로 해석한다. 실패 시 후보를 안내."""
    if law_type not in _LAW_TYPES:
        _fail(f"law_type은 {'/'.join(_LAW_TYPES)} 중 하나여야 합니다: {law_type!r}")
    try:
        repo = find_repo(None)  # 아카이브 없음은 sys.exit로 나온다
    except SystemExit as e:
        _fail(str(e.code))
    law_dir = resolve_law_dir(repo, law_name)
    if law_dir is None:
        hits = suggest_laws(repo, law_name)
        _fail(f"법령을 찾을 수 없습니다: {law_name!r}"
              + (f" — 비슷한 이름: {', '.join(hits)}" if hits
                 else " — search_laws 도구로 법령명을 먼저 찾아보세요."))
    file_path = law_dir / f"{law_type}.md"
    if not file_path.is_file():
        available = [t for t in _LAW_TYPES if (law_dir / f"{t}.md").is_file()]
        _fail(f"'{law_dir.name}'에는 {law_type} 파일이 없습니다."
              + (f" 조회 가능한 종류: {', '.join(available)}" if available else ""))
    return repo, law_dir.name, file_path.relative_to(repo).as_posix()


def lookup_article(law_name: str, article: str, law_type: str = "법률",
                   as_of: str | None = None) -> dict:
    """법령명과 조번호로 조문 전문을 일차자료 출처 URL과 함께 조회한다.

    law_name: 법령명 (예: "민법", "주택임대차보호법"). 정확한 이름을 모르면
        search_laws로 먼저 찾는다.
    article: 조번호 (예: "2", "839의2", "제839조의2").
    law_type: "법률"(기본) / "시행령" / "시행규칙".
    as_of: "YYYY-MM-DD" — 지정하면 그 날짜 당시 공포되어 있던 버전을 조회한다
        (사건 발생 시점의 조문이 필요할 때).
    """
    try:
        repo, dir_name, rel_path = _law_file(law_name, law_type)
        text, commit = read_at(repo, rel_path, as_of)
    except SystemExit as e:  # read_at/find_repo는 CLI용이라 sys.exit로 실패한다
        _fail(str(e.code))
    fm, body = parse_frontmatter(text)
    try:
        num, sub = parse_article_number(article)
    except ValueError as e:
        _fail(str(e))
    article_text = extract_article(body, num, sub)
    label = f"제{num}조" + (f"의{sub}" if sub else "")
    if article_text is None:
        _fail(f"{fm.제목 or law_name}에서 {label}을(를) 찾지 못했습니다."
              " list_articles 도구로 조문 목차를 확인해 보세요.")
    result = {
        "law_title": fm.제목 or dir_name,
        "law_type": law_type,
        "label": label,
        "text": article_text,
        "source_url": fm.출처,
        "공포일자": fm.공포일자,
        "시행일자": fm.시행일자,
        "disclaimer": _DISCLAIMER,
    }
    if as_of:
        result["as_of"] = as_of
        result["commit"] = commit
    return result


def list_law_articles(law_name: str, law_type: str = "법률") -> dict:
    """법령의 조문 목차(제n조와 제목 목록)를 반환한다."""
    repo, dir_name, rel_path = _law_file(law_name, law_type)
    text, _ = read_at(repo, rel_path, None)
    fm, body = parse_frontmatter(text)
    return {
        "law_title": fm.제목 or dir_name,
        "law_type": law_type,
        "articles": list_articles(body),
        "source_url": fm.출처,
    }


def search_laws(keyword: str) -> dict:
    """키워드를 포함하는 법령명 목록을 반환한다 (법령명을 모를 때 사용)."""
    try:
        repo = find_repo(None)
    except SystemExit as e:
        _fail(str(e.code))
    return {"keyword": keyword, "laws": suggest_laws(repo, keyword)}


def semantic_search(query: str, preset: str | None = None,
                    law_filter: str | None = None, top_k: int = 5,
                    law_type: str = "법률", model: str = DEFAULT_MODEL,
                    ctx: Context = None) -> dict:
    """자연어 질의로 조문을 하이브리드 검색한다 (임베딩 + 형태소 어휘, RRF 융합).

    일상어 질의를 그대로 넣어도 된다 — 임베딩이 일상어와 조문 언어의 간극을
    메운다. 법률용어로 재구성한 질의를 추가로 시도해 결과를 비교해도 좋다.

    preset: 주제별 법령 묶음 — 가족/노동/주거/교통/형사/소비자/금전/개인정보.
    law_filter: 법령명 부분일치 키워드 (preset과 동시 지정 불가).
    범위를 지정하지 않으면 아카이브 전체(3천여 법령)라 색인 시간 문제로
    거부될 수 있다 — preset이나 law_filter로 좁히는 것을 권장.
    첫 색인은 수 분 걸릴 수 있으며 진행 상황이 progress 알림으로 전송된다.

    요구 사항: PostgreSQL + pgvector, law-cli[semantic] 설치.
    """
    from . import semantic  # 무거운 의존성은 사용 시에만 로드

    if preset and law_filter:
        _fail("preset과 law_filter는 함께 쓸 수 없습니다. 하나만 지정하세요.")
    if preset and preset not in PRESETS:
        _fail(f"알 수 없는 preset: {preset!r} (사용 가능: {', '.join(PRESETS)})")

    progress_fn = None
    if ctx is not None:
        def progress_fn(i, total, msg):
            _notify(ctx, ctx.report_progress, float(i), float(total),
                    f"임베딩 [{i}/{total}] {msg}")

    try:
        repo = find_repo(None)
        if ctx is not None:
            _notify(ctx, ctx.info, f'하이브리드 검색 준비: "{query}" — 대상 동기화 확인 중')
        scope, n_files, hits = semantic.search(
            repo, query, model=model, law_type=law_type, law_filter=law_filter,
            top_k=top_k, db=DEFAULT_DB, index_all=False, preset=preset,
            progress_fn=progress_fn)
    except semantic.SearchScopeError as e:
        _fail(str(e))
    except SystemExit as e:  # PgStore·임베더 로드 실패는 sys.exit로 나온다
        _fail(str(e.code))
    return {
        "query": query,
        "scope": scope,
        "law_count": n_files,
        "results": [
            {
                "law_name": c.law_name,
                "law_title": c.law_title,
                "law_type": c.law_type,
                "label": c.label,
                "title": c.title,
                "semantic_rank": vec_rank,
                "lexical_rank": lex_rank,
                "text": c.text,
                "source_url": c.source_url,
            }
            for c, vec_rank, lex_rank in hits
        ],
        "disclaimer": _DISCLAIMER,
    }


def main() -> int:
    try:
        try:
            from mcp.server.mcpserver import MCPServer  # mcp 2.x
        except ImportError:
            from mcp.server.fastmcp import FastMCP as MCPServer  # mcp 1.x
    except ImportError:
        print(_MISSING_MCP_MSG, file=sys.stderr)
        return 1

    server = MCPServer(
        "law-kr",
        instructions=(
            "대한민국 법령 조문 조회·검색 도구. 사용자의 일상어 표현을 법조문"
            " 언어로 해석하는 것은 당신(LLM)의 역할이고, 이 도구는 정확한 조문"
            " 전문과 일차자료 출처 URL을 제공한다. 조문 위치를 모르면"
            " semantic_search로 탐색하고, 인용할 때는 lookup_article로 전문을"
            " 확인한 뒤 반드시 source_url을 함께 제시하라. 법률 자문이 아니라"
            " 참고용 조회라는 점을 사용자에게 알려야 한다."
        ),
    )
    for fn in (lookup_article, list_law_articles, search_laws, semantic_search):
        server.tool()(fn)
    server.run()  # stdio
    return 0


if __name__ == "__main__":
    sys.exit(main())

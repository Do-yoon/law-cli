# 대한민국 법령 조문 조회 CLI
#
# legalize-kr Git 아카이브에서 법령명·조번호로 조문을 찾아 출력한다.
# - 인용의 근거는 항상 아카이브의 원문이며, 모든 출력에 일차자료(정부 사이트) URL을 붙인다
# - --as-of 로 특정 날짜 당시의 조문을 조회한다 (git log --before → git show)
#
# 외부 의존성 없음 (표준 라이브러리 + git 명령만 사용)
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# 조문 헤딩: "##### 제2조 (정의)", "### 제839조의2 (재산분할청구권)" 등
# 제목 괄호는 선택적이며, 중첩 괄호가 있어도 줄 끝까지 취한다
_HEADING_RE = re.compile(r"^(#{1,6})\s*제(\d+)조(?:의(\d+))?(?:\s*\((.*)\))?\s*$")
# 임의 헤딩(장·절 포함) — 조문의 경계
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s")
# 조번호 입력: "2", "제2조", "839의2", "제839조의2"
_ARTICLE_INPUT_RE = re.compile(r"^(?:제)?(\d+)(?:조)?(?:의(\d+))?$")

_LAW_TYPES = ("법률", "시행령", "시행규칙")

# --preset 법령 스코프 프리셋 — 일반인 상담 빈도가 높은 주제별 법령 묶음.
# 부분일치가 아닌 정규화 동일 일치로 매칭한다 ("민법" 부분일치는 "난민법"까지 잡는다).
# 구성 법령명은 legalize-kr 아카이브의 kr/ 디렉토리명 기준.
PRESETS = {
    "가족": ["민법", "가족관계의등록등에관한법률", "가사소송법"],
    "노동": [
        "근로기준법", "최저임금법", "근로자퇴직급여보장법",
        "기간제및단시간근로자보호등에관한법률",
        "남녀고용평등과일ㆍ가정양립지원에관한법률", "산업재해보상보험법",
    ],
    "주거": ["주택임대차보호법", "상가건물임대차보호법", "공동주택관리법"],
    "교통": ["도로교통법", "교통사고처리특례법", "자동차손해배상보장법"],
    "형사": [
        "형법", "형사소송법", "경범죄처벌법",
        "스토킹범죄의처벌등에관한법률", "성폭력범죄의처벌등에관한특례법",
        "형의실효등에관한법률",
    ],
    "소비자": [
        "소비자기본법", "전자상거래등에서의소비자보호에관한법률",
        "약관의규제에관한법률", "할부거래에관한법률", "방문판매등에관한법률",
    ],
    "금전": [
        "이자제한법", "대부업등의등록및금융이용자보호에관한법률",
        "채권의공정한추심에관한법률",
    ],
    "개인정보": ["개인정보보호법", "정보통신망이용촉진및정보보호등에관한법률"],
}

# 저장소 자동 탐지 순서: 환경변수 → 현재 디렉토리 → 홈 디렉토리
_DEFAULT_REPO_CANDIDATES = (
    Path("legalize-kr"),
    Path.home() / "legalize-kr",
    Path.home() / "work" / "legal" / "legalize-kr",
)


@dataclass
class Frontmatter:
    제목: str = ""
    공포일자: str = ""
    시행일자: str = ""
    상태: str = ""
    출처: str = ""
    기타: dict[str, str] = field(default_factory=dict)


def parse_frontmatter(text: str) -> tuple[Frontmatter, str]:
    """문서 선두의 YAML frontmatter를 파싱해 (메타데이터, 본문)을 반환한다."""
    fm = Frontmatter()
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return fm, text
    body_start = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_start = i + 1
            break
    if body_start is None:
        return fm, text
    for raw in lines[1 : body_start - 1]:
        if ":" not in raw or raw.startswith((" ", "-", "\t")):
            continue  # 리스트 항목·들여쓰기 값은 조회에 불필요
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip().strip("'\"")
        if hasattr(fm, key) and key != "기타":
            setattr(fm, key, value)
        else:
            fm.기타[key] = value
    return fm, "\n".join(lines[body_start:])


def normalize_name(name: str) -> str:
    """법령명 비교용 정규화 — 공백 제거, 중점 통일, NFC."""
    name = unicodedata.normalize("NFC", name)
    name = name.replace(" ", "").replace("·", "ㆍ")  # · → ㆍ
    return name


def parse_article_number(raw: str) -> tuple[int, int | None]:
    """조번호 입력을 (조, 의N)으로 해석한다. 예: '839의2' → (839, 2)"""
    m = _ARTICLE_INPUT_RE.match(raw.strip())
    if not m:
        raise ValueError(
            f"조번호를 해석할 수 없습니다: {raw!r} (예: 2 / 제2조 / 839의2 / 제839조의2)"
        )
    return int(m.group(1)), int(m.group(2)) if m.group(2) else None


def extract_article(body: str, num: int, sub: int | None) -> str | None:
    """본문에서 제num조(의sub) 조문 블록을 추출한다. 경계는 다음 임의 헤딩."""
    lines = body.split("\n")
    start = None
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and int(m.group(2)) == num:
            m_sub = int(m.group(3)) if m.group(3) else None
            if m_sub == sub:
                start = i
                break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if _ANY_HEADING_RE.match(lines[j]):
            end = j
            break
    return "\n".join(lines[start:end]).rstrip()


def list_articles(body: str) -> list[str]:
    """본문의 조문 헤딩 목록(목차)을 반환한다."""
    toc = []
    for line in body.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            label = f"제{m.group(2)}조" + (f"의{m.group(3)}" if m.group(3) else "")
            title = f" ({m.group(4)})" if m.group(4) else ""
            toc.append(label + title)
    return toc


def find_repo(cli_path: str | None) -> Path:
    """legalize-kr 저장소 위치를 찾는다. 없으면 안내 메시지와 함께 종료."""
    candidates = []
    if cli_path:
        candidates.append(Path(cli_path).expanduser())
    env = os.environ.get("LEGALIZE_KR_REPO")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.extend(_DEFAULT_REPO_CANDIDATES)
    for c in candidates:
        if (c / "kr").is_dir():
            return c
    sys.exit(
        "legalize-kr 저장소를 찾을 수 없습니다.\n"
        "아래 중 한 가지 방법으로 준비해 주세요:\n"
        "  1) git clone https://github.com/legalize-kr/legalize-kr.git\n"
        "  2) --repo <경로> 옵션 지정\n"
        "  3) 환경변수 LEGALIZE_KR_REPO=<경로> 설정"
    )


def resolve_law_dir(repo: Path, name: str) -> Path | None:
    """법령명으로 kr/ 아래 디렉토리를 찾는다 (정규화 일치)."""
    kr = repo / "kr"
    direct = kr / name
    if direct.is_dir():
        return direct
    want = normalize_name(name)
    for d in kr.iterdir():
        if d.is_dir() and normalize_name(d.name) == want:
            return d
    return None


def suggest_laws(repo: Path, keyword: str, limit: int = 15) -> list[str]:
    """키워드를 포함하는 법령명 후보를 반환한다."""
    want = normalize_name(keyword)
    hits = sorted(
        d.name for d in (repo / "kr").iterdir()
        if d.is_dir() and want in normalize_name(d.name)
    )
    return hits[:limit]


def read_at(repo: Path, rel_path: str, as_of: str | None) -> tuple[str, str | None]:
    """파일 내용을 읽는다. as_of가 있으면 해당 날짜 당시 커밋의 내용을 (내용, commit) 으로 반환."""
    if as_of is None:
        return (repo / rel_path).read_text(encoding="utf-8"), None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", as_of):
        sys.exit(f"--as-of 날짜 형식이 잘못되었습니다: {as_of!r} (예: 2023-06-30)")
    commit = _git(repo, "log", f"--before={as_of}T23:59:59", "-1", "--format=%H", "--", rel_path)
    if not commit:
        sys.exit(f"{as_of} 이전의 버전이 없습니다 (해당 시점에 이 법령이 아카이브에 존재하지 않음)")
    return _git(repo, "show", f"{commit}:{rel_path}"), commit


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"git 명령 실패: {result.stderr.strip()}")
    return result.stdout.strip()


def _print_header(fm: Frontmatter, law_type: str, as_of: str | None, commit: str | None):
    print("=" * 60)
    print(f"{fm.제목 or '(제목 없음)'} — {law_type}")
    meta = []
    if fm.공포일자:
        meta.append(f"공포 {fm.공포일자}")
    if fm.시행일자:
        meta.append(f"시행 {fm.시행일자}")
    if fm.상태:
        meta.append(fm.상태)
    if meta:
        print("  " + " / ".join(meta))
    if as_of:
        print(f"  ※ {as_of} 당시 버전 (commit {commit[:12] if commit else '?'})")
    print("=" * 60)


def _print_source(fm: Frontmatter):
    print()
    print("-" * 60)
    if fm.출처:
        print(f"출처(일차자료): {fm.출처}")
    print("이 출력은 참고용 조회 결과입니다. 반드시 위 출처의 원문으로 확인하세요.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="law-cli",
        description="대한민국 법령 조문 조회 — 법령명과 조번호를 입력하면 해당 조문과 출처 URL을 보여줍니다.",
        epilog=(
            "사용 예:\n"
            "  law-cli 민법 839의2                  # 민법 제839조의2 조회\n"
            "  law-cli 스토킹범죄의처벌등에관한법률 18 --as-of 2023-06-30\n"
            "  law-cli 민법 --toc                   # 조문 목차\n"
            "  law-cli --search 스토킹              # 법령명 검색\n"
            '  law-cli --semantic "재산 분할" --law-filter 민법   # 자연어 의미 검색\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("law", nargs="?", help="법령명 (예: 민법)")
    parser.add_argument("article", nargs="?", help="조번호 (예: 2 / 제2조 / 839의2)")
    parser.add_argument("--type", choices=_LAW_TYPES, default="법률",
                        help="법령 종류 (기본: 법률)")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD",
                        help="해당 날짜 당시의 조문을 조회 (예: 사건 발생일)")
    parser.add_argument("--toc", action="store_true", help="조문 목차를 출력")
    parser.add_argument("--search", metavar="키워드", help="키워드로 법령명을 검색")
    parser.add_argument("--repo", help="legalize-kr 저장소 경로")

    semantic_group = parser.add_argument_group(
        "의미 검색 (Hugging Face 임베딩 모델 + PostgreSQL/pgvector)"
    )
    semantic_group.add_argument("--semantic", metavar="질의문",
                                help='자연어로 조문을 의미 검색 (예: --semantic "재산 분할 청구")')
    semantic_group.add_argument("--model", default=None, metavar="HF모델",
                                help="Hugging Face 임베딩 모델명 (기본: BAAI/bge-m3)")
    semantic_group.add_argument("--top-k", type=int, default=5, metavar="N",
                                help="결과 개수 (기본: 5)")
    semantic_group.add_argument("--law-filter", metavar="키워드",
                                help="법령명 부분일치로 검색·색인 범위를 좁힘 (권장)")
    semantic_group.add_argument("--preset", choices=list(PRESETS),
                                help="주제별 법령 묶음으로 범위를 좁힘 (예: --preset 가족)")
    semantic_group.add_argument("--db", default=None, metavar="DB명",
                                help="PostgreSQL 데이터베이스명 (기본: $LAW_CLI_DB 또는 law_cli)")
    semantic_group.add_argument("--index-all", action="store_true",
                                help="--law-filter 없이 아카이브 전체 색인을 허용")
    args = parser.parse_args(argv)

    if args.preset and args.law_filter:
        parser.error("--preset과 --law-filter는 함께 쓸 수 없습니다. 하나만 지정하세요.")
    if args.preset and not args.semantic:
        parser.error("--preset은 --semantic과 함께 사용합니다.")

    repo = find_repo(args.repo)

    if args.semantic:
        from . import semantic  # 무거운 의존성은 --semantic 사용 시에만 로드

        return semantic.run(
            repo, args.semantic,
            model=args.model or semantic.DEFAULT_MODEL,
            law_type=args.type,
            law_filter=args.law_filter,
            top_k=args.top_k,
            db=args.db or semantic.DEFAULT_DB,
            index_all=args.index_all,
            preset=args.preset,
        )

    if args.search:
        hits = suggest_laws(repo, args.search)
        if not hits:
            print(f"'{args.search}'를 포함하는 법령을 찾지 못했습니다.")
            return 1
        print(f"'{args.search}' 검색 결과 ({len(hits)}건):")
        for name in hits:
            print(f"  {name}")
        return 0

    if not args.law:
        parser.print_help()
        return 1

    law_dir = resolve_law_dir(repo, args.law)
    if law_dir is None:
        print(f"법령을 찾을 수 없습니다: {args.law}")
        hits = suggest_laws(repo, args.law)
        if hits:
            print("혹시 이 법령인가요?")
            for name in hits:
                print(f"  {name}")
        else:
            print(f"'law-cli --search 키워드' 로 법령명을 먼저 찾아보세요.")
        return 1

    file_path = law_dir / f"{args.type}.md"
    rel_path = file_path.relative_to(repo).as_posix()
    if args.as_of is None and not file_path.is_file():
        print(f"'{law_dir.name}'에는 {args.type} 파일이 없습니다.")
        available = [t for t in _LAW_TYPES if (law_dir / f"{t}.md").is_file()]
        if available:
            print(f"조회 가능한 종류: {', '.join(available)}")
        return 1

    text, commit = read_at(repo, rel_path, args.as_of)
    fm, body = parse_frontmatter(text)

    if args.toc or not args.article:
        _print_header(fm, args.type, args.as_of, commit)
        toc = list_articles(body)
        if not toc:
            print("(조문 헤딩을 찾지 못했습니다 — 이 문서는 조문 구조가 아닐 수 있습니다)")
        for label in toc:
            print(f"  {label}")
        _print_source(fm)
        return 0

    try:
        num, sub = parse_article_number(args.article)
    except ValueError as e:
        print(e)
        return 1

    article = extract_article(body, num, sub)
    label = f"제{num}조" + (f"의{sub}" if sub else "")
    if article is None:
        print(f"{fm.제목 or args.law}에서 {label}을(를) 찾지 못했습니다.")
        print("'--toc' 옵션으로 조문 목차를 확인해 보세요.")
        return 1

    _print_header(fm, args.type, args.as_of, commit)
    print()
    print(article)
    _print_source(fm)
    return 0


if __name__ == "__main__":
    sys.exit(main())

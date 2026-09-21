# law-cli 전체 설계 덱(pptx) 생성 스크립트
#
# 실행: uv run --with python-pptx python docs/make_design_deck.py [--lang ko]
# - 문자열을 STRINGS 딕셔너리에 모아 두었으므로, 영어판은 STRINGS["en"]을
#   채운 뒤 --lang en 으로 생성한다 (한국어판은 gitignore, 영어판만 커밋).
from __future__ import annotations

import argparse
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

FONT = "Apple SD Gothic Neo"  # macOS 기본 한글 글꼴 (영어판도 무난)
NAVY = RGBColor(0x1F, 0x36, 0x64)
BLUE = RGBColor(0x2E, 0x74, 0xB5)
GRAY = RGBColor(0x59, 0x59, 0x59)
LIGHT = RGBColor(0xEF, 0xF3, 0xFA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def _set_font(run, size, bold=False, color=NAVY):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def _textbox(slide, x, y, w, h):
    box = slide.shapes.add_textbox(x, y, w, h)
    box.text_frame.word_wrap = True
    return box


def add_title(slide, text, subtitle=None):
    box = _textbox(slide, Inches(0.6), Inches(0.35), SLIDE_W - Inches(1.2), Inches(0.9))
    p = box.text_frame.paragraphs[0]
    _set_font(p.add_run(), 30, bold=True)
    p.runs[0].text = text
    if subtitle:
        p2 = box.text_frame.add_paragraph()
        r = p2.add_run()
        r.text = subtitle
        _set_font(r, 14, color=GRAY)
    # 제목 아래 구분선
    line = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(1.25), SLIDE_W - Inches(1.2), Emu(28575))
    line.fill.solid()
    line.fill.fore_color.rgb = BLUE
    line.line.fill.background()


def add_bullets(slide, items, x=Inches(0.8), y=Inches(1.6), w=None, h=None, size=17):
    """items: (들여쓰기레벨, 텍스트, 강조여부) 튜플 목록."""
    box = _textbox(slide, x, y, w or (SLIDE_W - Inches(1.6)), h or Inches(5.4))
    tf = box.text_frame
    for i, (level, text, bold) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = level
        p.space_after = Pt(8)
        r = p.add_run()
        r.text = ("• " if level == 0 else "– ") + text
        _set_font(r, size - level * 2, bold=bold, color=NAVY if level == 0 else GRAY)
    return box


def add_box(slide, x, y, w, h, title, body="", fill=LIGHT, title_color=NAVY):
    """아키텍처 다이어그램용 라운드 박스."""
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = BLUE
    shape.line.width = Pt(1.2)
    tf = shape.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = title
    _set_font(r, 14, bold=True, color=title_color)
    if body:
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run()
        r2.text = body
        _set_font(r2, 11, color=GRAY)
    return shape


def add_arrow(slide, from_shape, to_shape):
    """두 박스를 화살표 커넥터로 잇는다 (중심 기준 직선)."""
    x1 = from_shape.left + from_shape.width // 2
    y1 = from_shape.top + from_shape.height
    x2 = to_shape.left + to_shape.width // 2
    y2 = to_shape.top
    conn = slide.shapes.add_connector(2, x1, y1, x2, y2)  # 2 = 직선
    conn.line.color.rgb = BLUE
    conn.line.width = Pt(2)
    # 화살촉
    conn.line._get_or_add_ln().append(_arrow_tail())
    return conn


def _arrow_tail():
    from pptx.oxml.ns import qn
    from lxml import etree
    el = etree.SubElement(etree.Element(qn("a:ln")), qn("a:tailEnd"))
    el.set("type", "arrow")
    return el


def build(lang: str, out_path: Path):
    s = STRINGS[lang]
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    blank = prs.slide_layouts[6]

    # ── 1. 표지 ──────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(2.4), SLIDE_W, Inches(2.0))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY
    band.line.fill.background()
    tf = band.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = s["cover_title"]
    _set_font(r, 40, bold=True, color=WHITE)
    p2 = tf.add_paragraph()
    p2.alignment = PP_ALIGN.CENTER
    r2 = p2.add_run()
    r2.text = s["cover_sub"]
    _set_font(r2, 16, color=LIGHT)
    foot = _textbox(slide, Inches(0.6), Inches(6.7), SLIDE_W - Inches(1.2), Inches(0.5))
    rf = foot.text_frame.paragraphs[0].add_run()
    rf.text = s["cover_foot"]
    _set_font(rf, 12, color=GRAY)
    foot.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    # ── 2. 목표와 원칙 ────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    add_title(slide, s["goals_title"])
    add_bullets(slide, s["goals_bullets"])

    # ── 3. 전체 아키텍처 ──────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    add_title(slide, s["arch_title"], s["arch_sub"])
    src = add_box(slide, Inches(4.4), Inches(1.6), Inches(4.5), Inches(0.95),
                  s["arch_src"], s["arch_src_body"])
    core = add_box(slide, Inches(4.4), Inches(3.0), Inches(4.5), Inches(0.95),
                   s["arch_core"], s["arch_core_body"])
    det = add_box(slide, Inches(1.0), Inches(4.5), Inches(5.0), Inches(1.05),
                  s["arch_det"], s["arch_det_body"])
    sem = add_box(slide, Inches(7.3), Inches(4.5), Inches(5.0), Inches(1.05),
                  s["arch_sem"], s["arch_sem_body"])
    out = add_box(slide, Inches(4.4), Inches(6.1), Inches(4.5), Inches(0.95),
                  s["arch_out"], s["arch_out_body"], fill=RGBColor(0xFD, 0xF3, 0xE3))
    for a, b in ((src, core), (core, det), (core, sem), (det, out), (sem, out)):
        add_arrow(slide, a, b)

    # ── 4. 현재 구현 (결정적 조회) ────────────────────────────
    slide = prs.slides.add_slide(blank)
    add_title(slide, s["core_title"], s["core_sub"])
    add_bullets(slide, s["core_bullets"])

    # ── 5. 의미 검색 확장 — CLI 설계 ─────────────────────────
    slide = prs.slides.add_slide(blank)
    add_title(slide, s["sem_title"], s["sem_sub"])
    add_bullets(slide, s["sem_bullets"])

    # ── 6. 데이터 모델 (law_chunks) ──────────────────────────
    slide = prs.slides.add_slide(blank)
    add_title(slide, s["schema_title"], s["schema_sub"])
    rows = s["schema_rows"]
    table_shape = slide.shapes.add_table(
        len(rows) + 1, 3, Inches(0.8), Inches(1.55), SLIDE_W - Inches(1.6), Inches(5.3))
    table = table_shape.table
    table.columns[0].width = Inches(2.4)
    table.columns[1].width = Inches(2.2)
    table.columns[2].width = Inches(7.1)
    for j, head in enumerate(s["schema_head"]):
        cell = table.cell(0, j)
        cell.text = head
        _set_font(cell.text_frame.paragraphs[0].runs[0], 13, bold=True, color=WHITE)
    for i, row in enumerate(rows, 1):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.text = val
            _set_font(cell.text_frame.paragraphs[0].runs[0], 12,
                      bold=(j == 0), color=NAVY if j == 0 else GRAY)

    # ── 7. 설계 판단 ─────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    add_title(slide, s["why_title"])
    add_bullets(slide, s["why_bullets"], size=16)

    # ── 8. 배포·운영 ─────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    add_title(slide, s["ops_title"])
    add_bullets(slide, s["ops_bullets"])

    # ── 9. 로드맵 ────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    add_title(slide, s["roadmap_title"])
    add_bullets(slide, s["roadmap_bullets"])

    prs.save(out_path)
    print(f"저장: {out_path}")


STRINGS = {
    "ko": {
        "cover_title": "law-cli 전체 설계",
        "cover_sub": "대한민국 법령 조문 조회 + 의미 검색 CLI — legalize-kr 아카이브 기반",
        "cover_foot": "2026-08 · 내부 설계 문서 (한국어판) · 영어판을 GitHub에 공개 예정",
        "goals_title": "목표와 원칙",
        "goals_bullets": [
            (0, "목표: 법령명·조번호로 조문을 일차자료 출처 URL과 함께 조회하는 CLI", True),
            (0, "확장: Hugging Face 임베딩 모델로 자연어 의미 검색 (조문 위치를 모를 때의 탐색 경로)", True),
            (0, "원칙 1 — 이중 경로", False),
            (1, "인용은 결정적 조회(파일·git), 탐색은 의미 검색(임베딩) — 역할을 섞지 않는다", False),
            (0, "원칙 2 — 파생물 원칙", False),
            (1, "벡터스토어는 정본(legalize-kr)의 파생물. 언제든 DROP 후 전량 재생성 가능해야 한다", False),
            (0, "원칙 3 — 법률 자문 아님", False),
            (1, "모든 출력에 일차자료 URL과 참고용 고지를 동봉한다", False),
        ],
        "arch_title": "전체 아키텍처",
        "arch_sub": "정본 → 코어 → 두 경로(결정적 조회 / 의미 검색) → 출력",
        "arch_src": "legalize-kr 정본",
        "arch_src_body": "Git 아카이브 · kr/법령명/{법률,시행령,시행규칙}.md",
        "arch_core": "law-cli 코어",
        "arch_core_body": "frontmatter 파싱 · 조문 헤딩 파싱 · 조 단위 청킹 (표준 라이브러리만)",
        "arch_det": "결정적 조회",
        "arch_det_body": "법령명 + 조번호 · --as-of는 git log/show로 시점 조회",
        "arch_sem": "하이브리드 검색 (확장)",
        "arch_sem_body": "HF 임베딩(기본 bge-m3) + Kiwi→tsvector · RRF 융합 → PostgreSQL (law_chunks)",
        "arch_out": "터미널 출력",
        "arch_out_body": "조문 전문 / top-k 결과 · 출처 URL · 재조회 명령 안내",
        "core_title": "현재 구현 — 결정적 조회",
        "core_sub": "외부 의존성 0 (표준 라이브러리 + git 명령)",
        "core_bullets": [
            (0, "조문 조회: law-cli 민법 839의2 → 제839조의2 블록 추출", False),
            (1, "조문 헤딩 정규식(제n조·제n조의m) + 다음 헤딩까지를 경계로 추출", False),
            (0, "시점 조회: --as-of YYYY-MM-DD", False),
            (1, "git log --before로 당시 커밋을 찾아 git show로 그 시점의 조문을 표시", False),
            (0, "목차·검색: --toc(조문 목록), --search(법령명 키워드)", False),
            (0, "저장소 자동 탐지: --repo → $LEGALIZE_KR_REPO → 관례 경로", False),
            (0, "테스트: 픽스처 문자열 기반 단위 테스트 (git 불필요)", False),
        ],
        "sem_title": "하이브리드 검색 확장 — CLI 설계",
        "sem_sub": 'law-cli --semantic "질의문" [--model HF모델] [--law-filter 키워드] [--top-k N] [--db 이름]',
        "sem_bullets": [
            (0, "흐름", True),
            (1, "대상 수집(--law-filter·--type) → 파일 해시 비교로 증분 동기화(변경분만 색인)", False),
            (1, "색인 두 갈래: ① 원문 임베딩(pgvector) ② Kiwi 형태소 토큰 → tsvector(GIN)", False),
            (1, "질의도 두 경로로 검색 → RRF(1/(60+순위) 합산) 융합 → 경로별 순위와 함께 출력", False),
            (0, "일반인 타겟: 일상어 간극은 임베딩(주)이, 정확 용어 일치는 어휘 경로(보조)가 담당", False),
            (0, "모델: --model로 임의 Hugging Face 모델 지정 (기본 BAAI/bge-m3)", False),
            (0, "안전 가드: 필터 없이 미색인 200개 초과 시 중단 — --index-all로만 전체 색인", False),
            (0, "지연 로드: sentence-transformers·psycopg는 --semantic 사용 시에만 임포트", False),
            (1, "기존 조회 기능은 계속 의존성 0으로 동작 (optional extra로 분리 설치)", False),
        ],
        "schema_title": "데이터 모델 — law_chunks (PostgreSQL + pgvector)",
        "schema_sub": "1행 = 1조문 · 동기화 인덱스 (model, law_name, law_type)",
        "schema_head": ["컬럼", "타입", "설명"],
        "schema_rows": [
            ["model", "TEXT", "임베딩 모델명 — 모델별 벡터 공간 분리 키"],
            ["law_name / law_type", "TEXT", "kr/ 디렉토리명 + 종류(법률·시행령·시행규칙) — 재조회 키"],
            ["law_title / label / title", "TEXT", "표시용: 정식 제목 · 제n조(의m) · 조문 제목"],
            ["chunk_text", "TEXT", "임베딩 원문 (법령명 + 조문 전문, 문맥 보강)"],
            ["source_url", "TEXT", "일차자료(law.go.kr) URL — 모든 결과에 동봉"],
            ["file_hash", "TEXT", "원본 파일 sha1 — 증분 동기화 키"],
            ["embedding", "VECTOR", "차원 미고정 — 모델마다 차원이 달라도 한 테이블 사용"],
            ["tokens / tsv", "TEXT / TSVECTOR", "Kiwi 내용어 토큰 → 'simple' tsvector 생성 컬럼 (GIN 인덱스)"],
        ],
        "why_title": "설계 판단 — 왜 이렇게 채택했나",
        "why_bullets": [
            (0, "조문 단위 청킹 (1행 = 1조문)", True),
            (1, "조문은 의미적으로 자기완결적인 최소 단위 → 검색 품질과 인용 정확성 모두 확보", False),
            (1, "결과의 law_name + label로 결정적 조회 명령을 즉시 재구성 (탐색 → 인용 연결)", False),
            (0, "VECTOR 차원 미고정 + model 컬럼", True),
            (1, "요구사항이 '임의 HF 모델 지원' — 모델마다 차원 상이(bge-m3=1024, MiniLM=384)", False),
            (1, "트레이드오프: HNSW 불가 → 정확 스캔. 필터로 좁힌 규모(수천~수만 행)에선 충분", False),
            (0, "file_hash 증분 동기화", True),
            (1, "아카이브 git pull 후 변경된 법령만 삭제·재임베딩 — 전량 재색인 불필요", False),
            (0, "하이브리드(임베딩 主 + Kiwi→tsvector 補, RRF 융합)", True),
            (1, "일반인은 법률용어를 모름 → 의미 검색이 주. 정확 단어 일치는 어휘 경로가 구제", False),
            (1, "형태소 분석기는 임베딩과 별개 경로 — 모델 토크나이저는 서브워드라 색인에 부적합", False),
            (0, "대규모·고정모델 인덱스(HNSW)는 별도 시스템 담당 — 역할 중복 회피", True),
        ],
        "ops_title": "배포·운영",
        "ops_bullets": [
            (0, "패키징: uv 기반 (pyproject.toml + uv.lock)", False),
            (1, "개발: uv sync --extra semantic · 설치: uv tool install \"law-cli[semantic]\"", False),
            (0, "optional extra semantic: sentence-transformers, psycopg[binary], kiwipiepy", False),
            (1, "코어는 의존성 0 유지 — 조회만 쓰는 사용자는 가볍게 설치", False),
            (0, "DB: 로컬 PostgreSQL + pgvector 확장 · 기본 DB명 law_cli ($LAW_CLI_DB)", False),
            (1, "DB 없으면 자동 생성 시도, pgvector 미설치 시 안내 후 중단", False),
            (0, "문서: 한국어판(내부, gitignore) → 영어판 번역 후 GitHub 커밋", False),
        ],
        "roadmap_title": "로드맵",
        "roadmap_bullets": [
            (0, "1) [완료] CLI 연결: --semantic 옵션군을 argparse에 연결 + 단위 테스트", False),
            (0, "2) [완료] 통합 테스트: 로컬 PostgreSQL 스모크 테스트 (없으면 자동 스킵)", False),
            (0, "3) [완료] README 갱신: 의미 검색 사용법·DB 준비 절차", False),
            (0, "4) 설계 문서 영어판 생성 → GitHub 커밋 (한국어판은 gitignore 유지)", False),
            (0, "5) (검토) 법령 스코프 프리셋, 판례 코퍼스 확장 여부", False),
        ],
    },
    "en": {
        "cover_title": "law-cli — Overall Design",
        "cover_sub": "Korean statute lookup + semantic search CLI — built on the legalize-kr archive",
        "cover_foot": "2026-08 · Design document (English edition, translated from the internal Korean edition)",
        "goals_title": "Goals & Principles",
        "goals_bullets": [
            (0, "Goal: a CLI that looks up statute articles by law name and article number, always with the primary-source URL", True),
            (0, "Extension: natural-language semantic search via Hugging Face embedding models (the discovery path when you don't know where an article lives)", True),
            (0, "Principle 1 — Two separate paths", False),
            (1, "Citation uses deterministic lookup (files + git); discovery uses semantic search (embeddings) — never mix the roles", False),
            (0, "Principle 2 — Derived-data principle", False),
            (1, "The vector store is a derivative of the canonical archive (legalize-kr); it must always be DROP-able and fully rebuildable", False),
            (0, "Principle 3 — Not legal advice", False),
            (1, "Every output carries the primary-source URL and a reference-only disclaimer", False),
        ],
        "arch_title": "Architecture",
        "arch_sub": "Canonical source → core → two paths (deterministic lookup / semantic search) → output",
        "arch_src": "legalize-kr (canonical)",
        "arch_src_body": "Git archive · kr/<law name>/{Act, Enforcement Decree, Enforcement Rule}.md",
        "arch_core": "law-cli core",
        "arch_core_body": "Frontmatter parsing · article-heading parsing · per-article chunking (stdlib only)",
        "arch_det": "Deterministic lookup",
        "arch_det_body": "Law name + article number · --as-of uses git log/show for point-in-time lookup",
        "arch_sem": "Hybrid search (extension)",
        "arch_sem_body": "HF embeddings (default bge-m3) + Kiwi→tsvector · RRF fusion → PostgreSQL (law_chunks)",
        "arch_out": "Terminal output",
        "arch_out_body": "Full article text / top-k results · source URL · re-lookup command hint",
        "core_title": "Current Implementation — Deterministic Lookup",
        "core_sub": "Zero external dependencies (stdlib + git commands)",
        "core_bullets": [
            (0, "Article lookup: law-cli 민법 839의2 → extracts the Article 839-2 block", False),
            (1, "Article-heading regex (Article n / Article n-m) + extraction bounded by the next heading", False),
            (0, "Point-in-time lookup: --as-of YYYY-MM-DD", False),
            (1, "git log --before finds the commit of that date; git show renders the article as of then", False),
            (0, "TOC & search: --toc (article list), --search (law-name keyword)", False),
            (0, "Archive auto-detection: --repo → $LEGALIZE_KR_REPO → conventional paths", False),
            (0, "Tests: fixture-string-based unit tests (no git required)", False),
        ],
        "sem_title": "Hybrid Search Extension — CLI Design",
        "sem_sub": 'law-cli --semantic "query" [--model HF-model] [--law-filter keyword] [--top-k N] [--db name]',
        "sem_bullets": [
            (0, "Flow", True),
            (1, "Collect targets (--law-filter, --type) → incremental sync by file-hash comparison (index only what changed)", False),
            (1, "Two-way indexing: ① raw-text embeddings (pgvector) ② Kiwi morpheme tokens → tsvector (GIN)", False),
            (1, "Queries run through both paths → RRF fusion (Σ 1/(60+rank)) → results shown with per-path ranks", False),
            (0, "Aimed at laypeople: embeddings (primary) bridge everyday language; the lexical path (secondary) guarantees exact term matches", False),
            (0, "Models: any Hugging Face model via --model (default BAAI/bge-m3)", False),
            (0, "Safety guard: without a filter, abort if >200 laws are unindexed — full indexing only via --index-all", False),
            (0, "Lazy loading: sentence-transformers and psycopg are imported only when --semantic is used", False),
            (1, "The core lookup keeps working with zero dependencies (semantic ships as an optional extra)", False),
        ],
        "schema_title": "Data Model — law_chunks (PostgreSQL + pgvector)",
        "schema_sub": "1 row = 1 article · sync index on (model, law_name, law_type)",
        "schema_head": ["Column", "Type", "Description"],
        "schema_rows": [
            ["model", "TEXT", "Embedding model name — partition key separating vector spaces per model"],
            ["law_name / law_type", "TEXT", "kr/ directory name + kind (Act, Enforcement Decree, Enforcement Rule) — re-lookup key"],
            ["law_title / label / title", "TEXT", "For display: official title · Article n(-m) · article heading"],
            ["chunk_text", "TEXT", "Embedding source text (law name + full article, for extra context)"],
            ["source_url", "TEXT", "Primary-source (law.go.kr) URL — attached to every result"],
            ["file_hash", "TEXT", "sha1 of the source file — incremental-sync key"],
            ["embedding", "VECTOR", "Dimension left unfixed — one table serves models of any dimension"],
            ["tokens / tsv", "TEXT / TSVECTOR", "Kiwi content-word tokens → generated 'simple' tsvector column (GIN index)"],
        ],
        "why_title": "Design Decisions — Why This Shape",
        "why_bullets": [
            (0, "Per-article chunking (1 row = 1 article)", True),
            (1, "An article is the smallest semantically self-contained unit → good retrieval quality and precise citations", False),
            (1, "law_name + label in a result reconstructs the deterministic lookup command instantly (discovery → citation)", False),
            (0, "Unfixed VECTOR dimension + model column", True),
            (1, "The requirement is 'any HF model' — dimensions differ per model (bge-m3=1024, MiniLM=384)", False),
            (1, "Trade-off: no HNSW → exact scan; fine at filtered scale (thousands to tens of thousands of rows)", False),
            (0, "file_hash incremental sync", True),
            (1, "After a git pull of the archive, only changed laws are deleted and re-embedded — no full re-index", False),
            (0, "Hybrid (embeddings primary + Kiwi→tsvector secondary, RRF fusion)", True),
            (1, "Laypeople don't know legal terms → semantic search leads; exact word matches are rescued by the lexical path", False),
            (1, "The morphological analyzer is a separate path from the embeddings — model tokenizers are subword-based and unsuitable for lexical indexing", False),
            (0, "Large-scale, fixed-model indexes (HNSW) belong to a separate system — avoid duplicating roles", True),
        ],
        "ops_title": "Packaging & Operations",
        "ops_bullets": [
            (0, "Packaging: uv-based (pyproject.toml + uv.lock)", False),
            (1, "Development: uv sync --extra semantic · Install: uv tool install \"law-cli[semantic]\"", False),
            (0, "Optional extra semantic: sentence-transformers, psycopg[binary], kiwipiepy", False),
            (1, "The core stays dependency-free — lookup-only users get a light install", False),
            (0, "DB: local PostgreSQL + pgvector extension · default DB name law_cli ($LAW_CLI_DB)", False),
            (1, "Missing DB is auto-created; missing pgvector aborts with guidance", False),
            (0, "Docs: Korean edition (internal, gitignored) → this English edition committed to GitHub", False),
        ],
        "roadmap_title": "Roadmap",
        "roadmap_bullets": [
            (0, "1) [done] CLI wiring: --semantic option group in argparse + unit tests", False),
            (0, "2) [done] Integration tests: PostgreSQL smoke tests (auto-skip when unavailable)", False),
            (0, "3) [done] README refresh: semantic-search usage and DB setup", False),
            (0, "4) English edition of this design deck → committed to GitHub (Korean edition stays gitignored)", False),
            (0, "5) (Under review) statute scope presets; whether to add a case-law corpus", False),
        ],
    },
}


def main():
    ap = argparse.ArgumentParser(description="law-cli 설계 덱 생성")
    ap.add_argument("--lang", default="ko", choices=list(STRINGS))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out = args.out or Path(__file__).parent / f"law-cli-design-{args.lang}.pptx"
    build(args.lang, out)


if __name__ == "__main__":
    main()

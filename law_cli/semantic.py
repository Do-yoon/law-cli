# 하이브리드 의미 검색 — HF 임베딩 모델 + Kiwi 형태소 tsvector + PostgreSQL(pgvector)
#
# 흐름: legalize-kr 조문을 조 단위로 청킹 → ① 임베딩(원문 그대로) ② Kiwi 형태소
#       토큰(어휘 색인용) 두 갈래로 law_chunks 에 저장 → 질의를 같은 두 경로로
#       검색한 뒤 RRF(Reciprocal Rank Fusion)로 순위를 융합한다.
# - 임베딩(주 경로): 일상어 질의와 조문 언어의 어휘 간극을 의미로 메운다.
# - tsvector(보조 경로): 조문에 그대로 나오는 단어의 정확 일치를 보장한다.
#   한국어는 조사·어미 때문에 형태소 분석 없이는 tsvector 재현율이 나오지 않아
#   Kiwi로 내용어만 추출해 'simple' 설정으로 색인한다. 임베딩 모델에는 형태소
#   분석 결과를 먹이지 않는다 (자연문으로 학습된 모델이라 오히려 품질 저하).
# - 저장 행은 (모델명, 법령, 종류, 파일 해시) 기준으로 증분 동기화한다.
#   파일이 바뀌면 해당 법령 행을 지우고 다시 임베딩한다.
# - 무거운 의존성(sentence-transformers, kiwipiepy, psycopg)은 이 모듈에서만
#   임포트한다. 기존 조회 기능은 여전히 표준 라이브러리만으로 동작한다.
from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import _ANY_HEADING_RE, _HEADING_RE, PRESETS, normalize_name, parse_frontmatter

DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_DB = os.environ.get("LAW_CLI_DB", "law_cli")

# --law-filter 없이 이 수를 넘는 미동기화 파일이 있으면 --index-all을 요구한다
# (아카이브 전체 3천여 법령을 실수로 임베딩하는 것을 방지)
_INDEX_ALL_THRESHOLD = 200

# 임베딩 함수: 문자열 목록 → 정규화된 벡터 목록
EmbedFn = Callable[[Sequence[str]], Sequence[Sequence[float]]]
# 토큰화 함수: 문자열 목록 → 공백으로 이어붙인 형태소 토큰 문자열 목록
TokenizeFn = Callable[[Sequence[str]], list[str]]
# 진행 콜백: (현재, 전체, 메시지) — MCP progress 알림 등 stderr 밖 전달용
ProgressFn = Callable[[int, int, str], None]

# RRF 융합 상수 (관례값 60 — 상위권 순위 차이를 완만하게 반영)
_RRF_K = 60
# 융합 전 각 경로에서 가져올 후보 폭
_POOL_MIN = 50

_MISSING_DEPS_MSG = (
    "의미 검색에는 추가 의존성이 필요합니다. 다음으로 설치하세요:\n"
    "  uv sync --extra semantic              (개발 중)\n"
    '  uv tool install "law-cli[semantic]"   (도구로 설치)'
)


@dataclass
class Chunk:
    """조문 단위 청크 — 검색 결과 표시에 필요한 메타데이터를 함께 가진다."""
    law_name: str   # kr/ 아래 디렉토리명 (재조회용)
    law_type: str   # 법률 / 시행령 / 시행규칙
    law_title: str  # frontmatter 제목
    label: str      # 제n조 / 제n조의m
    title: str      # 조문 제목 (없으면 빈 문자열)
    text: str       # 조문 전문 (임베딩 원문)
    source_url: str


def split_articles(body: str) -> list[tuple[str, str, str]]:
    """본문을 조문 단위로 분할해 (라벨, 제목, 전문) 목록을 반환한다."""
    lines = body.split("\n")
    starts: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            label = f"제{m.group(2)}조" + (f"의{m.group(3)}" if m.group(3) else "")
            starts.append((i, label, m.group(4) or ""))
    out = []
    for k, (start, label, title) in enumerate(starts):
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if _ANY_HEADING_RE.match(lines[j]):
                end = j
                break
        text = "\n".join(lines[start:end]).strip()
        if text:
            out.append((label, title, text))
    return out


def chunk_file(law_name: str, law_type: str, raw_text: str) -> tuple[str, list[Chunk]]:
    """파일 내용을 (파일 해시, 청크 목록)으로 변환한다."""
    file_hash = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()
    fm, body = parse_frontmatter(raw_text)
    chunks = [
        Chunk(law_name, law_type, fm.제목 or law_name, label, title,
              # 임베딩 원문에 법령명을 붙여 짧은 조문의 문맥을 보강한다
              f"{fm.제목 or law_name} {label}\n{text}", fm.출처)
        for label, title, text in split_articles(body)
    ]
    return file_hash, chunks


def collect_law_files(repo: Path, law_type: str,
                      law_filter: str | Sequence[str] | None) -> list[tuple[str, Path]]:
    """검색 대상 (법령명, 파일 경로) 목록.

    law_filter가 문자열이면 법령명 부분일치, 목록이면 정규화 동일 일치(프리셋용 —
    부분일치는 "민법"이 "난민법"까지 잡으므로 프리셋은 정확한 법령명으로 좁힌다).
    """
    if isinstance(law_filter, str):
        want = normalize_name(law_filter)
        match = lambda name: want in name
    elif law_filter is not None:
        exact = {normalize_name(x) for x in law_filter}
        match = lambda name: name in exact
    else:
        match = None
    out = []
    for d in sorted((repo / "kr").iterdir()):
        if not d.is_dir():
            continue
        if match and not match(normalize_name(d.name)):
            continue
        f = d / f"{law_type}.md"
        if f.is_file():
            out.append((d.name, f))
    return out


def _vec_text(vec: Sequence[float]) -> str:
    """pgvector 텍스트 표기 — psycopg 파라미터로 넘긴 뒤 ::vector 로 캐스트한다."""
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


class PgStore:
    """law_chunks 테이블에 대한 저장·조회. 스키마는 최초 사용 시 생성한다."""

    _SCHEMA = """
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS law_chunks (
      id         BIGSERIAL PRIMARY KEY,
      model      TEXT NOT NULL,
      law_name   TEXT NOT NULL,
      law_type   TEXT NOT NULL,
      law_title  TEXT NOT NULL,
      label      TEXT NOT NULL,
      title      TEXT NOT NULL DEFAULT '',
      chunk_text TEXT NOT NULL,
      source_url TEXT NOT NULL DEFAULT '',
      file_hash  TEXT NOT NULL,
      embedding  VECTOR NOT NULL,
      -- 어휘 검색 경로: Kiwi 형태소 토큰(공백 구분) → 'simple' tsvector
      tokens     TEXT NOT NULL DEFAULT '',
      tsv        TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', tokens)) STORED
    );
    -- 구버전 테이블 마이그레이션 (컬럼이 없으면 추가 — 기존 행은 재동기화로 채운다)
    ALTER TABLE law_chunks ADD COLUMN IF NOT EXISTS tokens TEXT NOT NULL DEFAULT '';
    ALTER TABLE law_chunks ADD COLUMN IF NOT EXISTS tsv TSVECTOR
      GENERATED ALWAYS AS (to_tsvector('simple', tokens)) STORED;
    CREATE INDEX IF NOT EXISTS law_chunks_sync_idx
      ON law_chunks (model, law_name, law_type);
    CREATE INDEX IF NOT EXISTS law_chunks_tsv_idx ON law_chunks USING gin (tsv);
    """

    def __init__(self, dbname: str):
        try:
            import psycopg  # 지연 임포트 — --semantic 사용 시에만 필요
        except ImportError:
            sys.exit(_MISSING_DEPS_MSG)

        self._psycopg = psycopg
        try:
            self.conn = psycopg.connect(dbname=dbname)
        except psycopg.OperationalError as e:
            if "does not exist" in str(e):
                self._create_database(dbname)
                self.conn = psycopg.connect(dbname=dbname)
            else:
                sys.exit(
                    f"PostgreSQL 접속 실패 (dbname={dbname}): {e}\n"
                    "로컬 PostgreSQL이 실행 중인지 확인하세요 (pg_isready)."
                )
        try:
            # 주의: psycopg3의 `with conn:` 은 블록 종료 시 커넥션을 닫는다 — transaction() 사용
            with self.conn.transaction():
                self.conn.execute(self._SCHEMA)
        except psycopg.Error as e:
            sys.exit(
                f"스키마 생성 실패: {e}\n"
                "pgvector 확장이 설치되어 있어야 합니다 (예: brew install pgvector)."
            )

    def _create_database(self, dbname: str):
        # 데이터베이스가 없으면 maintenance DB를 통해 만들어 준다
        with self._psycopg.connect(dbname="postgres", autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{dbname}"')
        print(f"데이터베이스 {dbname} 를 새로 만들었습니다.", file=sys.stderr)

    def close(self):
        self.conn.close()

    def synced_hashes(self, model: str) -> dict[tuple[str, str], str]:
        """이미 저장된 (법령명, 종류) → 파일 해시.

        토큰이 비어 있는 행이 하나라도 있으면 (구버전 스키마로 색인된 법령)
        목록에서 제외해 재동기화를 유도한다.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT law_name, law_type, file_hash FROM law_chunks WHERE model = %s"
                " GROUP BY law_name, law_type, file_hash HAVING bool_and(tokens <> '')",
                (model,),
            )
            return {(n, t): h for n, t, h in cur.fetchall()}

    def replace_law(self, model: str, law_name: str, law_type: str,
                    file_hash: str, chunks: list[Chunk],
                    vectors: Sequence[Sequence[float]], tokens: Sequence[str]):
        """한 법령 파일의 행을 통째로 교체한다 (증분 동기화 단위)."""
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM law_chunks WHERE model = %s AND law_name = %s AND law_type = %s",
                (model, law_name, law_type),
            )
            cur.executemany(
                "INSERT INTO law_chunks"
                " (model, law_name, law_type, law_title, label, title,"
                "  chunk_text, source_url, file_hash, embedding, tokens)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)",
                [
                    (model, c.law_name, c.law_type, c.law_title, c.label, c.title,
                     c.text, c.source_url, file_hash, _vec_text(v), tk)
                    for c, v, tk in zip(chunks, vectors, tokens)
                ],
            )

    _SELECT = ("SELECT id, law_name, law_type, law_title, label, title,"
               " chunk_text, source_url FROM law_chunks WHERE model = %s")

    @staticmethod
    def _rows_to_hits(rows) -> list[tuple[int, Chunk]]:
        return [(rid, Chunk(n, t, lt, la, ti, tx, u))
                for rid, n, t, lt, la, ti, tx, u in rows]

    def search(self, model: str, query_vec: Sequence[float],
               law_names: Sequence[str] | None, limit: int) -> list[tuple[int, Chunk]]:
        """의미 경로: cosine 거리 오름차순 상위 limit. (행 id, 청크) 순위 목록."""
        qv = _vec_text(query_vec)
        sql, params = self._SELECT, [model]
        if law_names is not None:
            sql += " AND law_name = ANY(%s)"
            params.append(list(law_names))
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params += [qv, limit]
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return self._rows_to_hits(cur.fetchall())

    def lexical_search(self, model: str, query_tokens: Sequence[str],
                       law_names: Sequence[str] | None, limit: int) -> list[tuple[int, Chunk]]:
        """어휘 경로: 형태소 토큰 OR 매칭을 ts_rank_cd 내림차순으로 상위 limit."""
        # to_tsquery 구문 문자를 제거하고 OR로 잇는다 (일반인 질의는 재현율 우선)
        safe = [t for t in ("".join(ch for ch in tok if ch.isalnum()) for tok in query_tokens) if t]
        if not safe:
            return []
        tsquery = " | ".join(safe)
        sql = self._SELECT + " AND tsv @@ to_tsquery('simple', %s)"
        params: list = [model, tsquery]
        if law_names is not None:
            sql += " AND law_name = ANY(%s)"
            params.append(list(law_names))
        sql += " ORDER BY ts_rank_cd(tsv, to_tsquery('simple', %s)) DESC LIMIT %s"
        params += [tsquery, limit]
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return self._rows_to_hits(cur.fetchall())


def load_embedder(model_name: str) -> EmbedFn:
    """Hugging Face 모델을 sentence-transformers로 로드해 임베딩 함수를 만든다."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.exit(_MISSING_DEPS_MSG)
    print(f"모델 로드 중: {model_name} …", file=sys.stderr)
    model = SentenceTransformer(model_name)

    def embed(texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return model.encode(list(texts), normalize_embeddings=True,
                            show_progress_bar=False).tolist()

    return embed


# 어휘 색인에 남길 Kiwi 품사: 명사류·수사·외래어/한자/숫자·동사/형용사 어간·어근
_KIWI_KEEP_TAGS = frozenset(
    {"NNG", "NNP", "NNB", "NR", "SL", "SH", "SN", "VV", "VA", "XR"}
)


def load_tokenizer() -> TokenizeFn:
    """Kiwi 형태소 분석기를 로드해 내용어 토큰화 함수를 만든다 (어휘 검색 전용)."""
    try:
        from kiwipiepy import Kiwi
    except ImportError:
        sys.exit(_MISSING_DEPS_MSG)
    kiwi = Kiwi()

    def tokenize(texts: Sequence[str]) -> list[str]:
        return [
            " ".join(tok.form for tok in kiwi.tokenize(t) if tok.tag in _KIWI_KEEP_TAGS)
            for t in texts
        ]

    return tokenize


def rrf_fuse(vec_hits: Sequence[tuple[int, Chunk]], lex_hits: Sequence[tuple[int, Chunk]],
             top_k: int, k: int = _RRF_K) -> list[tuple[Chunk, int | None, int | None]]:
    """두 경로의 순위를 RRF(Σ 1/(k+순위))로 융합해 (청크, 의미순위, 어휘순위)를 반환."""
    scores: dict[int, float] = {}
    entries: dict[int, dict] = {}
    for key, hits in (("vec", vec_hits), ("lex", lex_hits)):
        for rank, (rid, chunk) in enumerate(hits, 1):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
            e = entries.setdefault(rid, {"chunk": chunk, "vec": None, "lex": None})
            e[key] = rank
    order = sorted(scores, key=lambda rid: -scores[rid])
    return [(entries[r]["chunk"], entries[r]["vec"], entries[r]["lex"])
            for r in order[:top_k]]


def sync(store: PgStore, repo: Path, model: str, law_type: str,
         files: list[tuple[str, Path]], embed_fn: EmbedFn,
         tokenize_fn: TokenizeFn, progress_fn: ProgressFn | None = None) -> int:
    """변경·미등록 파일만 임베딩·토큰화해 저장한다. 처리한 파일 수를 반환."""
    synced = store.synced_hashes(model)
    done = 0
    stale = []
    for law_name, path in files:
        raw = path.read_text(encoding="utf-8")
        file_hash, chunks = chunk_file(law_name, law_type, raw)
        if synced.get((law_name, law_type)) == file_hash:
            continue
        stale.append((law_name, file_hash, chunks))
    for i, (law_name, file_hash, chunks) in enumerate(stale, 1):
        print(f"임베딩 [{i}/{len(stale)}] {law_name} ({len(chunks)}개 조문)", file=sys.stderr)
        if progress_fn:
            progress_fn(i, len(stale), f"{law_name} ({len(chunks)}개 조문)")
        texts = [c.text for c in chunks]
        vectors = embed_fn(texts) if chunks else []
        tokens = tokenize_fn(texts) if chunks else []
        store.replace_law(model, law_name, law_type, file_hash, chunks, vectors, tokens)
        done += 1
    return done


def count_unsynced(store: PgStore, model: str, law_type: str,
                   files: list[tuple[str, Path]]) -> int:
    """임베딩이 필요한 파일 수 (해시 비교)."""
    synced = store.synced_hashes(model)
    n = 0
    for law_name, path in files:
        raw = path.read_text(encoding="utf-8")
        file_hash, _ = chunk_file(law_name, law_type, raw)
        if synced.get((law_name, law_type)) != file_hash:
            n += 1
    return n


def _article_arg(label: str) -> str:
    """'제9조의2' → law-cli 재조회용 인수 '9의2'."""
    return label.removeprefix("제").replace("조", "", 1)


class SearchScopeError(Exception):
    """검색을 진행할 수 없는 상태 — 메시지를 사용자에게 그대로 보여준다."""


def search(repo: Path, query: str, *, model: str, law_type: str,
           law_filter: str | Sequence[str] | None, top_k: int, db: str, index_all: bool,
           preset: str | None = None, store: PgStore | None = None,
           embed_fn: EmbedFn | None = None, tokenize_fn: TokenizeFn | None = None,
           progress_fn: ProgressFn | None = None,
           ) -> tuple[str, int, list[tuple[Chunk, int | None, int | None]]]:
    """하이브리드 검색 — 동기화 후 RRF 융합 결과를 구조화해 반환한다.

    반환: (범위 표시 문자열, 대상 법령 수, [(청크, 의미순위, 어휘순위)]).
    진행 불가 상태(대상 없음·전체 색인 가드)는 SearchScopeError로 알린다.
    store/embed_fn/tokenize_fn 은 테스트 주입용.
    """
    if preset:
        # CLI에서 --law-filter와의 동시 지정은 이미 거부됨 (choices로 이름도 검증됨)
        law_filter = PRESETS[preset]
    scope = (f"--preset {preset}" if preset
             else f"--law-filter {law_filter}" if law_filter else "전체")

    files = collect_law_files(repo, law_type, law_filter)
    if not files:
        raise SearchScopeError(f"검색 대상 법령이 없습니다 ({scope}, --type {law_type}).")

    store = store or PgStore(db)
    unsynced = count_unsynced(store, model, law_type, files)
    if unsynced > _INDEX_ALL_THRESHOLD and not law_filter and not index_all:
        raise SearchScopeError(
            f"임베딩이 필요한 법령이 {unsynced}개입니다 (전체 아카이브).\n"
            "시간이 오래 걸릴 수 있어 중단했습니다. 다음 중 하나를 선택하세요:\n"
            "  --law-filter 키워드   # 법령명을 좁혀서 색인 (권장)\n"
            f"  --preset 주제         # 주제별 법령 묶음 ({'·'.join(PRESETS)})\n"
            "  --index-all           # 전체 색인을 정말로 실행"
        )

    tokenize_fn = tokenize_fn or load_tokenizer()
    embed_fn = embed_fn or load_embedder(model)
    sync(store, repo, model, law_type, files, embed_fn, tokenize_fn, progress_fn)

    names = [n for n, _ in files]
    pool = max(top_k * 10, _POOL_MIN)
    query_vec = embed_fn([query])[0]
    query_tokens = tokenize_fn([query])[0].split()
    vec_hits = store.search(model, query_vec, names, pool)
    lex_hits = store.lexical_search(model, query_tokens, names, pool)
    return scope, len(files), rrf_fuse(vec_hits, lex_hits, top_k)


def run(repo: Path, query: str, *, model: str, law_type: str,
        law_filter: str | Sequence[str] | None, top_k: int, db: str, index_all: bool,
        preset: str | None = None, store: PgStore | None = None,
        embed_fn: EmbedFn | None = None, tokenize_fn: TokenizeFn | None = None,
        progress_fn: ProgressFn | None = None) -> int:
    """하이브리드 검색 CLI 실행 — search() 결과를 터미널에 출력한다."""
    try:
        scope, n_files, hits = search(
            repo, query, model=model, law_type=law_type, law_filter=law_filter,
            top_k=top_k, db=db, index_all=index_all, preset=preset,
            store=store, embed_fn=embed_fn, tokenize_fn=tokenize_fn,
            progress_fn=progress_fn)
    except SearchScopeError as e:
        print(e)
        return 1

    print("=" * 60)
    print(f'하이브리드 검색: "{query}"')
    print(f"  모델: {model} + 형태소 tsvector / 대상: {n_files}개 법령 ({scope}) / DB: {db}")
    print("=" * 60)
    if not hits:
        print("결과가 없습니다.")
        return 1
    for rank, (c, vec_rank, lex_rank) in enumerate(hits, 1):
        head = f"{c.label}" + (f" ({c.title})" if c.title else "")
        paths = " · ".join(
            f"{name} {r}위" for name, r in (("의미", vec_rank), ("어휘", lex_rank)) if r
        )
        print()
        print(f"[{rank}] ({paths})  {c.law_title} ({c.law_type}) {head}")
        # 미리보기: 헤딩 제외 첫 2줄
        preview = [l for l in c.text.split("\n")[1:] if l.strip()][:2]
        for line in preview:
            print(f"    {line.strip()}")
        if c.source_url:
            print(f"    출처: {c.source_url}")
        print(f"    전문 조회: law-cli {c.law_name} {_article_arg(c.label)}"
              + (f" --type {c.law_type}" if c.law_type != "법률" else ""))
    print()
    print("-" * 60)
    print("이 출력은 참고용 검색 결과입니다. 반드시 출처의 원문으로 확인하세요.")
    return 0

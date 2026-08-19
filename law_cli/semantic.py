# 의미 검색 — Hugging Face 임베딩 모델 + PostgreSQL(pgvector) 벡터스토어
#
# 흐름: legalize-kr 조문을 조 단위로 청킹 → 임베딩 → law_chunks 테이블에 저장
#       → 질의문 임베딩과의 cosine 거리로 top-k 조회.
# - 저장 행은 (모델명, 법령, 종류, 파일 해시) 기준으로 증분 동기화한다.
#   파일이 바뀌면 해당 법령 행을 지우고 다시 임베딩한다.
# - 무거운 의존성(sentence-transformers, psycopg)은 이 모듈에서만 임포트한다.
#   기존 조회 기능은 여전히 표준 라이브러리만으로 동작한다.
from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import _ANY_HEADING_RE, _HEADING_RE, normalize_name, parse_frontmatter

DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_DB = os.environ.get("LAW_CLI_DB", "law_cli")

# --law-filter 없이 이 수를 넘는 미동기화 파일이 있으면 --index-all을 요구한다
# (아카이브 전체 3천여 법령을 실수로 임베딩하는 것을 방지)
_INDEX_ALL_THRESHOLD = 200

# 임베딩 함수: 문자열 목록 → 정규화된 벡터 목록
EmbedFn = Callable[[Sequence[str]], Sequence[Sequence[float]]]

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


def collect_law_files(repo: Path, law_type: str, law_filter: str | None) -> list[tuple[str, Path]]:
    """검색 대상 (법령명, 파일 경로) 목록. law_filter는 법령명 부분일치."""
    want = normalize_name(law_filter) if law_filter else None
    out = []
    for d in sorted((repo / "kr").iterdir()):
        if not d.is_dir():
            continue
        if want and want not in normalize_name(d.name):
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
      embedding  VECTOR NOT NULL
    );
    CREATE INDEX IF NOT EXISTS law_chunks_sync_idx
      ON law_chunks (model, law_name, law_type);
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
        """이미 저장된 (법령명, 종류) → 파일 해시."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT law_name, law_type, file_hash FROM law_chunks WHERE model = %s",
                (model,),
            )
            return {(n, t): h for n, t, h in cur.fetchall()}

    def replace_law(self, model: str, law_name: str, law_type: str,
                    file_hash: str, chunks: list[Chunk], vectors: Sequence[Sequence[float]]):
        """한 법령 파일의 행을 통째로 교체한다 (증분 동기화 단위)."""
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM law_chunks WHERE model = %s AND law_name = %s AND law_type = %s",
                (model, law_name, law_type),
            )
            cur.executemany(
                "INSERT INTO law_chunks"
                " (model, law_name, law_type, law_title, label, title,"
                "  chunk_text, source_url, file_hash, embedding)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
                [
                    (model, c.law_name, c.law_type, c.law_title, c.label, c.title,
                     c.text, c.source_url, file_hash, _vec_text(v))
                    for c, v in zip(chunks, vectors)
                ],
            )

    def search(self, model: str, query_vec: Sequence[float],
               law_names: Sequence[str] | None, top_k: int) -> list[tuple[Chunk, float]]:
        """cosine 유사도 top-k. law_names가 있으면 해당 법령으로 한정한다."""
        qv = _vec_text(query_vec)
        sql = (
            "SELECT law_name, law_type, law_title, label, title, chunk_text, source_url,"
            " 1 - (embedding <=> %s::vector) AS score"
            " FROM law_chunks WHERE model = %s"
        )
        params: list = [qv, model]
        if law_names is not None:
            sql += " AND law_name = ANY(%s)"
            params.append(list(law_names))
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params += [qv, top_k]
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [
                (Chunk(n, t, lt, la, ti, tx, u), float(s))
                for n, t, lt, la, ti, tx, u, s in cur.fetchall()
            ]


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


def sync(store: PgStore, repo: Path, model: str, law_type: str,
         files: list[tuple[str, Path]], embed_fn: EmbedFn) -> int:
    """변경·미등록 파일만 임베딩해 저장한다. 임베딩한 파일 수를 반환."""
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
        vectors = embed_fn([c.text for c in chunks]) if chunks else []
        store.replace_law(model, law_name, law_type, file_hash, chunks, vectors)
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


def run(repo: Path, query: str, *, model: str, law_type: str,
        law_filter: str | None, top_k: int, db: str, index_all: bool,
        store: PgStore | None = None, embed_fn: EmbedFn | None = None) -> int:
    """의미 검색 실행 — 동기화 후 top-k를 출력한다. (store/embed_fn은 테스트 주입용)"""
    files = collect_law_files(repo, law_type, law_filter)
    if not files:
        print(f"검색 대상 법령이 없습니다 (--law-filter {law_filter!r}, --type {law_type}).")
        return 1

    store = store or PgStore(db)
    unsynced = count_unsynced(store, model, law_type, files)
    if unsynced > _INDEX_ALL_THRESHOLD and not law_filter and not index_all:
        print(
            f"임베딩이 필요한 법령이 {unsynced}개입니다 (전체 아카이브).\n"
            "시간이 오래 걸릴 수 있어 중단했습니다. 다음 중 하나를 선택하세요:\n"
            "  --law-filter 키워드   # 법령명을 좁혀서 색인 (권장)\n"
            "  --index-all           # 전체 색인을 정말로 실행"
        )
        return 1

    embed_fn = embed_fn or load_embedder(model)
    sync(store, repo, model, law_type, files, embed_fn)

    query_vec = embed_fn([query])[0]
    hits = store.search(model, query_vec, [n for n, _ in files], top_k)

    print("=" * 60)
    print(f'의미 검색: "{query}"')
    scope = f"--law-filter {law_filter}" if law_filter else "전체"
    print(f"  모델: {model} / 대상: {len(files)}개 법령 ({scope}) / DB: {db}")
    print("=" * 60)
    if not hits:
        print("결과가 없습니다.")
        return 1
    for rank, (c, score) in enumerate(hits, 1):
        head = f"{c.label}" + (f" ({c.title})" if c.title else "")
        print()
        print(f"[{rank}] 유사도 {score:.3f}  {c.law_title} ({c.law_type}) {head}")
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

# PostgreSQL 통합 스모크 테스트 — 로컬 PostgreSQL + pgvector가 "있을 때만" 실행
#
# 검증 범위: PgStore의 실제 DB 경로 — 스키마 생성(vector 확장·tsv 생성 컬럼·GIN),
# replace_law 의 벡터/토큰 INSERT, search(cosine)·lexical_search(to_tsquery),
# synced_hashes 기반 증분 동기화. 임베딩 모델은 내려받지 않고 conftest 의
# 가짜 임베더/토크나이저를 쓴다 (VECTOR 차원 미고정이라 64차원도 저장 가능).
import pytest
from conftest import fake_embed, fake_tokenize

psycopg = pytest.importorskip("psycopg", reason="semantic extra 미설치")

# 모듈 수준 가용성 확인 — PostgreSQL 미가동·pgvector 미설치 환경에서는 전체 스킵
try:
    with psycopg.connect(dbname="postgres", autocommit=True) as _conn:
        _has_vector = _conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
        ).fetchone()
except psycopg.OperationalError:
    pytest.skip("로컬 PostgreSQL이 실행 중이 아님", allow_module_level=True)
if _has_vector is None:
    pytest.skip("pgvector 확장이 설치되어 있지 않음", allow_module_level=True)

from law_cli import semantic
from law_cli.semantic import PgStore

_TEST_DB = "law_cli_test"


def _drop_test_db():
    with psycopg.connect(dbname="postgres", autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB}" WITH (FORCE)')


@pytest.fixture
def store():
    """테스트 전용 DB의 PgStore — DB 자동 생성 경로까지 함께 검증한다."""
    _drop_test_db()
    st = PgStore(_TEST_DB)
    yield st
    st.close()
    _drop_test_db()


def _run(repo, query, store, **overrides):
    kwargs = dict(model="fake", law_type="법률", law_filter=None,
                  top_k=3, db=_TEST_DB, index_all=True,
                  store=store, embed_fn=fake_embed, tokenize_fn=fake_tokenize)
    kwargs.update(overrides)
    return semantic.run(repo, query, **kwargs)


def test_스키마와_의미경로_검색(repo, store, capsys):
    rc = _run(repo, "테스트를 목적으로 한다", store)
    out = capsys.readouterr().out
    assert rc == 0
    # 질의와 겹치는 제1조(목적)가 1위 — cosine(<=>) 정렬이 실제 DB에서 동작
    first = out.split("[1]")[1].split("[2]")[0]
    assert "제1조" in first and "테스트 법률" in first
    assert "출처: https://www.law.go.kr/법령/테스트법률" in first
    assert "law-cli 테스트법률 1" in first


def test_어휘경로_tsquery_정확_용어(repo, store, capsys):
    # 의미 경로를 무력화해도(전부 동일 벡터) 정확 단어 "거짓"은 tsvector 경로가 잡는다
    def bad_embed(texts):
        return [[1.0] + [0.0] * 63 for _ in texts]

    rc = _run(repo, "거짓", store, embed_fn=bad_embed)
    out = capsys.readouterr().out
    assert rc == 0
    first = out.split("[1]")[1].split("[2]")[0]
    assert "제3조" in first and "어휘 1위" in first


def test_증분_동기화_재실행시_재임베딩_안함(repo, store, capsys):
    calls = []

    def counting_embed(texts):
        calls.append(list(texts))
        return fake_embed(texts)

    _run(repo, "질의", store, embed_fn=counting_embed)
    assert sum(len(c) for c in calls) == 4 + 1  # 최초 색인: 조문 4개 + 질의문 1개

    # 파일이 그대로면 synced_hashes 가 실제 DB에서 해시를 돌려줘 질의문만 임베딩
    calls.clear()
    _run(repo, "질의", store, embed_fn=counting_embed)
    assert [len(c) for c in calls] == [1]

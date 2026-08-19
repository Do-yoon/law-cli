# 의미 검색 로직 테스트 — PostgreSQL·모델 다운로드 없이 가짜 스토어/임베더로 검증
import math

import pytest

from law_cli import semantic
from law_cli.semantic import Chunk, chunk_file, collect_law_files, split_articles

FIXTURE = """---
제목: 테스트 법률
공포일자: 2023-07-11
시행일자: 2023-07-11
상태: 시행
출처: https://www.law.go.kr/법령/테스트법률
---

# 테스트 법률

## 제1장 총칙

##### 제1조 (목적)

이 법은 테스트를 목적으로 한다.

##### 제2조 (정의)

이 법에서 임베딩이란 문장을 벡터로 바꾸는 것을 말한다.

## 제2장 벌칙

##### 제3조 (벌칙)

거짓 진술을 한 자는 과태료를 부과한다.
"""

FIXTURE2 = """---
제목: 다른 법률
출처: https://www.law.go.kr/법령/다른법률
---

##### 제1조 (목적)

이 법은 전혀 다른 주제를 다룬다.
"""


def fake_embed(texts):
    """문자 바이그램 해싱 기반 결정적 가짜 임베딩 (정규화 포함)."""
    out = []
    for t in texts:
        vec = [0.0] * 64
        for a, b in zip(t, t[1:]):
            vec[hash(a + b) % 64] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        out.append([x / norm for x in vec])
    return out


class FakeStore:
    """PgStore와 같은 인터페이스의 인메모리 스토어."""

    def __init__(self):
        self.rows = {}  # (model, law_name, law_type) → (file_hash, [(Chunk, vec)])

    def synced_hashes(self, model):
        return {(n, t): h for (m, n, t), (h, _) in self.rows.items() if m == model}

    def replace_law(self, model, law_name, law_type, file_hash, chunks, vectors):
        self.rows[(model, law_name, law_type)] = (file_hash, list(zip(chunks, vectors)))

    def search(self, model, query_vec, law_names, top_k):
        hits = []
        for (m, n, t), (_, pairs) in self.rows.items():
            if m != model or (law_names is not None and n not in law_names):
                continue
            for chunk, vec in pairs:
                score = sum(a * b for a, b in zip(query_vec, vec))
                hits.append((chunk, score))
        hits.sort(key=lambda x: -x[1])
        return hits[:top_k]


@pytest.fixture
def repo(tmp_path):
    """kr/ 구조의 임시 아카이브."""
    for name, text in (("테스트법률", FIXTURE), ("다른법률", FIXTURE2)):
        d = tmp_path / "kr" / name
        d.mkdir(parents=True)
        (d / "법률.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_split_articles_조문_단위():
    _, body = semantic.parse_frontmatter(FIXTURE)
    arts = split_articles(body)
    assert [(a[0], a[1]) for a in arts] == [
        ("제1조", "목적"), ("제2조", "정의"), ("제3조", "벌칙"),
    ]
    # 장(章) 헤딩은 조문 텍스트에 포함되지 않는다
    assert all("제2장" not in a[2] for a in arts)


def test_chunk_file_메타데이터():
    file_hash, chunks = chunk_file("테스트법률", "법률", FIXTURE)
    assert len(file_hash) == 40  # sha1 hex
    assert all(c.law_title == "테스트 법률" for c in chunks)
    assert all(c.source_url.endswith("테스트법률") for c in chunks)
    # 임베딩 원문에는 문맥 보강용으로 법령명이 앞에 붙는다
    assert chunks[0].text.startswith("테스트 법률 제1조")


def test_chunk_file_해시는_내용_기준():
    h1, _ = chunk_file("a", "법률", FIXTURE)
    h2, _ = chunk_file("a", "법률", FIXTURE + "\n변경")
    assert h1 != h2


def test_collect_law_files_필터(repo):
    assert [n for n, _ in collect_law_files(repo, "법률", None)] == ["다른법률", "테스트법률"]
    # 부분일치 + 공백 정규화
    assert [n for n, _ in collect_law_files(repo, "법률", "테스트 법률")] == ["테스트법률"]
    assert collect_law_files(repo, "시행령", None) == []


def test_run_검색_상위결과(repo, capsys):
    store = FakeStore()
    rc = semantic.run(
        repo, "테스트를 목적으로 한다", model="fake", law_type="법률",
        law_filter=None, top_k=3, db="unused", index_all=True,
        store=store, embed_fn=fake_embed,
    )
    out = capsys.readouterr().out
    assert rc == 0
    # 질의와 겹치는 제1조(목적)가 1위여야 한다
    first = out.split("[1]")[1].split("[2]")[0]
    assert "제1조" in first and "테스트 법률" in first
    # 출처와 재조회 명령 안내가 붙는다
    assert "출처: https://www.law.go.kr/법령/테스트법률" in first
    assert "law-cli 테스트법률 1" in first


def test_run_law_filter_적용(repo, capsys):
    store = FakeStore()
    rc = semantic.run(
        repo, "아무 질의", model="fake", law_type="법률",
        law_filter="다른", top_k=5, db="unused", index_all=False,
        store=store, embed_fn=fake_embed,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "다른 법률" in out and "테스트 법률" not in out


def test_증분_동기화_같은_내용은_재임베딩_안함(repo):
    store = FakeStore()
    calls = []

    def counting_embed(texts):
        calls.append(list(texts))
        return fake_embed(texts)

    kwargs = dict(model="fake", law_type="법률", law_filter=None,
                  top_k=3, db="unused", index_all=True,
                  store=store, embed_fn=counting_embed)
    semantic.run(repo, "질의", **kwargs)
    embedded_first = sum(len(c) for c in calls)
    calls.clear()

    # 두 번째 실행: 파일이 그대로면 질의문 1건만 임베딩한다
    semantic.run(repo, "질의", **kwargs)
    assert [len(c) for c in calls] == [1]

    # 파일 하나를 바꾸면 그 법령만 재임베딩된다
    calls.clear()
    f = repo / "kr" / "다른법률" / "법률.md"
    f.write_text(FIXTURE2 + "\n##### 제2조 (추가)\n\n추가 조문.\n", encoding="utf-8")
    semantic.run(repo, "질의", **kwargs)
    total = sum(len(c) for c in calls)
    assert total == 2 + 1  # 다른법률 조문 2개 + 질의문
    assert embedded_first == 4 + 1  # 최초 색인: 두 법령의 조문 4개 + 질의문 1개


def test_전체색인_가드(repo, capsys, monkeypatch):
    # 필터·--index-all 없이 임계값을 넘으면 색인하지 않고 중단한다
    monkeypatch.setattr(semantic, "_INDEX_ALL_THRESHOLD", 1)
    store = FakeStore()
    rc = semantic.run(
        repo, "질의", model="fake", law_type="법률",
        law_filter=None, top_k=3, db="unused", index_all=False,
        store=store, embed_fn=fake_embed,
    )
    assert rc == 1
    assert "--index-all" in capsys.readouterr().out
    assert store.rows == {}  # 아무것도 색인되지 않았다


def test_대상_없음(repo, capsys):
    rc = semantic.run(
        repo, "질의", model="fake", law_type="법률",
        law_filter="존재하지않는법", top_k=3, db="unused", index_all=False,
        store=FakeStore(), embed_fn=fake_embed,
    )
    assert rc == 1
    assert "검색 대상 법령이 없습니다" in capsys.readouterr().out

# MCP 도구 함수 테스트 — 도구 본체는 순수 함수라 mcp SDK 없이 검증한다
# (FastMCP 등록·stdio 구동은 law-cli-mcp 실행 경로이고, 여기서는 반환값을 본다)
import pytest
from conftest import fake_embed, fake_tokenize

from law_cli import mcp_server, semantic


@pytest.fixture
def mcp_repo(repo, monkeypatch):
    """find_repo(None)가 임시 아카이브를 찾도록 환경변수로 고정한다."""
    monkeypatch.setenv("LEGALIZE_KR_REPO", str(repo))
    return repo


def test_lookup_article(mcp_repo):
    # 법령명은 공백 정규화로 해석된다
    r = mcp_server.lookup_article("테스트 법률", "2")
    assert r["law_title"] == "테스트 법률"
    assert r["label"] == "제2조"
    assert "임베딩이란" in r["text"]
    assert r["source_url"] == "https://www.law.go.kr/법령/테스트법률"
    assert "참고용" in r["disclaimer"]


def test_lookup_article_없는_조문은_목차_안내(mcp_repo):
    with pytest.raises(mcp_server.ToolError, match="list_articles"):
        mcp_server.lookup_article("테스트법률", "99")


def test_lookup_article_없는_법령은_후보_안내(mcp_repo):
    with pytest.raises(mcp_server.ToolError, match="비슷한 이름.*테스트법률"):
        mcp_server.lookup_article("테스트", "1")


def test_lookup_article_잘못된_law_type(mcp_repo):
    with pytest.raises(mcp_server.ToolError, match="법률/시행령/시행규칙"):
        mcp_server.lookup_article("테스트법률", "1", law_type="규칙")


def test_list_law_articles(mcp_repo):
    r = mcp_server.list_law_articles("테스트법률")
    assert r["articles"] == ["제1조 (목적)", "제2조 (정의)", "제3조 (벌칙)"]
    assert r["law_title"] == "테스트 법률"


def test_search_laws(mcp_repo):
    assert mcp_server.search_laws("테스트")["laws"] == ["테스트법률"]
    assert mcp_server.search_laws("없는키워드")["laws"] == []


def test_semantic_search_구조화_결과(mcp_repo, monkeypatch):
    # PgStore·임베더를 가짜로 대체해 semantic.search 경유 반환 구조를 검증한다
    from test_semantic import FakeStore
    store = FakeStore()
    orig = semantic.search

    def patched(repo, query, **kw):
        kw.update(store=store, embed_fn=fake_embed, tokenize_fn=fake_tokenize)
        return orig(repo, query, **kw)

    monkeypatch.setattr(semantic, "search", patched)
    r = mcp_server.semantic_search("테스트를 목적으로 한다", law_filter="테스트")
    assert r["scope"] == "--law-filter 테스트"
    top = r["results"][0]
    assert top["label"] == "제1조" and top["law_name"] == "테스트법률"
    assert top["semantic_rank"] == 1
    assert top["source_url"].endswith("테스트법률")
    assert "참고용" in r["disclaimer"]


def test_semantic_search_preset_filter_동시지정_거부(mcp_repo):
    with pytest.raises(mcp_server.ToolError, match="함께 쓸 수 없습니다"):
        mcp_server.semantic_search("질의", preset="가족", law_filter="민법")


def test_semantic_search_알수없는_preset(mcp_repo):
    with pytest.raises(mcp_server.ToolError, match="알 수 없는 preset"):
        mcp_server.semantic_search("질의", preset="없는주제")

# law-cli 핵심 로직 테스트 — 픽스처 문자열 기반 (git 불필요)
import pytest

from law_cli import (
    extract_article,
    list_articles,
    normalize_name,
    parse_article_number,
    parse_frontmatter,
)

FIXTURE = """---
제목: 테스트 법률
법령ID: '012345'
공포일자: 2023-07-11
시행일자: 2023-07-11
상태: 시행
출처: https://www.law.go.kr/법령/테스트법률
첨부파일: []
---

# 테스트 법률

## 제1장 총칙

##### 제1조 (목적)

이 법은 테스트를 목적으로 한다.

##### 제2조 (정의(용어))

이 법에서 사용하는 용어의 뜻은 다음과 같다.

##### 제2조의2 (특례)

특례 조문이다.

## 제2장 벌칙

##### 제3조

제목 없는 조문이다.
"""


def test_frontmatter():
    fm, body = parse_frontmatter(FIXTURE)
    assert fm.제목 == "테스트 법률"
    assert fm.공포일자 == "2023-07-11"
    assert fm.출처 == "https://www.law.go.kr/법령/테스트법률"
    assert body.lstrip().startswith("# 테스트 법률")


def test_frontmatter_없음():
    fm, body = parse_frontmatter("# 제목뿐인 문서\n본문")
    assert fm.제목 == ""
    assert body.startswith("# 제목뿐인 문서")


def test_extract_기본():
    _, body = parse_frontmatter(FIXTURE)
    art = extract_article(body, 1, None)
    assert art.startswith("##### 제1조 (목적)")
    assert "테스트를 목적으로 한다" in art
    # 다음 헤딩(제2조)은 포함하지 않는다
    assert "제2조" not in art


def test_extract_의N_구분():
    # 제2조와 제2조의2를 혼동하지 않아야 한다
    _, body = parse_frontmatter(FIXTURE)
    base = extract_article(body, 2, None)
    sub = extract_article(body, 2, 2)
    assert "용어의 뜻" in base and "특례" not in base
    assert "특례 조문" in sub


def test_extract_중첩괄호_제목():
    _, body = parse_frontmatter(FIXTURE)
    art = extract_article(body, 2, None)
    assert "정의(용어)" in art.split("\n")[0]


def test_extract_장_경계():
    # 장(章) 헤딩도 조문의 경계가 된다
    _, body = parse_frontmatter(FIXTURE)
    art = extract_article(body, 2, 2)
    assert "제2장" not in art


def test_extract_없는_조문():
    _, body = parse_frontmatter(FIXTURE)
    assert extract_article(body, 99, None) is None


def test_toc():
    _, body = parse_frontmatter(FIXTURE)
    assert list_articles(body) == [
        "제1조 (목적)",
        "제2조 (정의(용어))",
        "제2조의2 (특례)",
        "제3조",
    ]


@pytest.mark.parametrize("raw,expected", [
    ("2", (2, None)),
    ("제2조", (2, None)),
    ("839의2", (839, 2)),
    ("제839조의2", (839, 2)),
])
def test_조번호_해석(raw, expected):
    assert parse_article_number(raw) == expected


def test_조번호_오류():
    with pytest.raises(ValueError):
        parse_article_number("이상한입력")


def test_법령명_정규화():
    assert normalize_name("스토킹범죄의 처벌 등에 관한 법률") == normalize_name(
        "스토킹범죄의처벌등에관한법률"
    )
    assert normalize_name("가·나") == normalize_name("가ㆍ나")

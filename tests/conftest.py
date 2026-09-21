# 공용 테스트 픽스처 — 임시 아카이브와 가짜 임베더/토크나이저
# (단위 테스트 test_semantic.py 와 PostgreSQL 통합 테스트 test_semantic_pg.py 가 공유)
import math
import re

import pytest

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


def fake_tokenize(texts):
    """공백·구두점 분할 가짜 토크나이저 (형태소 분석기 대역)."""
    return [" ".join(re.findall(r"[0-9A-Za-z가-힣]+", t)) for t in texts]


@pytest.fixture
def repo(tmp_path):
    """kr/ 구조의 임시 아카이브."""
    for name, text in (("테스트법률", FIXTURE), ("다른법률", FIXTURE2)):
        d = tmp_path / "kr" / name
        d.mkdir(parents=True)
        (d / "법률.md").write_text(text, encoding="utf-8")
    return tmp_path

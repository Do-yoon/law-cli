# PyPI 릴리스 절차

배포는 GitHub Actions의 Trusted Publishing(OIDC)으로 이루어집니다 — API 토큰을
저장소에 보관할 필요가 없습니다. 최초 1회 설정 후에는 태그 push만으로 배포됩니다.

## 최초 1회 설정

1. **PyPI 계정** — [pypi.org](https://pypi.org)에서 계정 생성 후 2FA를 활성화합니다.
2. **Pending publisher 등록** — PyPI 로그인 → 계정 메뉴 → *Publishing* →
   *"Add a new pending publisher"* 에서 다음을 입력합니다:
   - PyPI Project Name: `law-cli`
   - Owner: `Do-yoon`
   - Repository name: `law-cli`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. **GitHub environment 생성** — 저장소 *Settings → Environments* 에서
   `pypi` 라는 이름의 environment를 만듭니다 (보호 규칙은 선택).

## 배포하기

```bash
# 1) pyproject.toml의 version을 올리고 커밋 (예: 0.2.0 → 0.3.0)
# 2) 버전과 일치하는 태그를 push
git tag v0.3.0
git push origin v0.3.0
```

태그 push로 `.github/workflows/publish.yml` 이 실행되어 `uv build` 산출물
(sdist + wheel)이 PyPI에 업로드됩니다. 결과는 Actions 탭에서 확인하세요.

배포 후 설치 확인:

```bash
uv tool install law-cli            # 코어(의존성 0)
uv tool install "law-cli[semantic]"  # 의미 검색 포함
```

## 대안: 수동 배포

Actions를 거치지 않으려면 PyPI에서 API 토큰을 발급받아 로컬에서:

```bash
uv build
uv publish --token pypi-XXXX...
```

## 주의

- 태그 버전과 `pyproject.toml`의 `version`을 반드시 일치시킵니다
  (불일치해도 업로드는 되지만 태그와 배포본이 어긋납니다).
- PyPI는 같은 버전의 재업로드를 허용하지 않습니다 — 실수했으면 버전을 올려
  다시 배포합니다.

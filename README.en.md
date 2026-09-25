[한국어](README.md) | **English**

# law-cli — Korean Statute Lookup CLI

A command-line tool that shows a statute article **together with its primary-source URL**
when you enter a law name and article number. It is built so that anyone — without legal
or Git knowledge — can take the first step of "reading the primary source accurately."

When you don't know where an article lives, **hybrid search** (`--semantic`) accepts
natural-language queries — it fuses semantic search by a Hugging Face embedding model
(default [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)) with tsvector lexical search
based on [Kiwi](https://github.com/bab2min/kiwipiepy) morphological analysis, using RRF
on top of PostgreSQL ([pgvector](https://github.com/pgvector/pgvector)).

The data comes from the [legalize-kr](https://github.com/legalize-kr/legalize-kr) archive
(built from the open data of the Korean National Law Information Center).

## Installation

Python 3.10 or later is required.

```bash
# 1) Prepare the statute archive (home directory recommended)
git clone https://github.com/legalize-kr/legalize-kr.git ~/legalize-kr

# 2) Install law-cli
git clone https://github.com/Do-yoon/law-cli.git
cd law-cli
pip install .        # or: uv tool install .
```

## Usage

```bash
# Look up Civil Act (민법) Article 839-2
law-cli 민법 839의2

# Stalking Punishment Act Article 18 — as it stood *before* the 2023 amendment
law-cli 스토킹범죄의처벌등에관한법률 18 --as-of 2023-06-30

# Show the table of articles
law-cli 민법 --toc

# When you don't know the law name: keyword search
law-cli --search 스토킹

# Enforcement decrees and rules
law-cli 민법 --type 시행령 --toc

# Natural-language semantic search — when you don't know where an article is
# (see "Hybrid Search" below)
law-cli --semantic "이혼할 때 재산을 나누는 규정" --law-filter 민법
```

### `--as-of` — the article as of a given date

Statutes keep being amended. "The article today" and "the article at the time of the
incident" may differ. With `--as-of DATE`, the tool shows the version that was
promulgated as of that date.

### Sample output

```
============================================================
스토킹범죄의 처벌 등에 관한 법률 — 법률
  공포 2021-04-20 / 시행 2021-10-21 / 시행
  ※ 2023-06-30 당시 버전 (commit d23de3f97821)
============================================================

##### 제18조 (스토킹범죄)

...article text...

------------------------------------------------------------
출처(일차자료): https://www.law.go.kr/법령/스토킹범죄의처벌등에관한법률
이 출력은 참고용 조회 결과입니다. 반드시 위 출처의 원문으로 확인하세요.
```

## Hybrid Search (`--semantic`)

Articles are chunked per article and indexed along two paths:

1. **Semantic path (primary)** — the raw article text is embedded with the model
   (pgvector, cosine). It bridges the vocabulary gap between everyday-language
   queries and statutory language.
2. **Lexical path (secondary)** — Kiwi morphological analysis extracts content words,
   indexed as a tsvector. It guarantees exact matches for words that appear verbatim
   in the article (e.g. "과태료", "접근").

A query runs through both paths, and the ranks are fused with **RRF (Reciprocal Rank
Fusion)** into a top-k list. Each result shows its per-path ranks (semantic n / lexical m).

### Setup

```bash
# 1) Install the extra dependencies
uv sync --extra semantic          # during development
uv tool install "law-cli[semantic]"   # when installing as a tool

# 2) PostgreSQL + pgvector (macOS example)
brew install postgresql@17 pgvector
brew services start postgresql@17
# The database (default: law_cli) is created automatically on first run
```

### Usage

```bash
# Narrow by law name (recommended — embeds once, reuses afterwards)
law-cli --semantic "이혼할 때 재산을 나누는 규정" --law-filter 민법

# Narrow by topic preset (가족=family, 노동=labor, 주거=housing, 교통=traffic,
# 형사=criminal, 소비자=consumer, 금전=money/debt, 개인정보=privacy)
law-cli --semantic "월급을 못 받았어요" --preset 노동

# Use a different Hugging Face embedding model
law-cli --semantic "query" --model intfloat/multilingual-e5-large --law-filter 민법

# Result count and law type
law-cli --semantic "query" --law-filter 민법 --top-k 10 --type 시행령

# Index the whole archive (3,000+ laws — slow, requires explicit consent)
law-cli --semantic "query" --index-all
```

- Embeddings are **incrementally synced** by (model, law, file hash) — after a
  `git pull` of the archive, only the changed laws are re-embedded.
- Each result carries the similarity, a preview, the source URL, and the deterministic
  lookup command (`law-cli <law> <article>`) to view the exact original text.
- `--preset` narrows the scope to a curated topic bundle. Unlike keyword partial
  matching (`--law-filter`), it only includes laws whose names match exactly after
  normalization — so a keyword like "민법" never drags in "난민법" (Refugee Act).
  It cannot be combined with `--law-filter`.
- The database name can be changed with `--db` or the `LAW_CLI_DB` environment variable.
- The vector store is a derivative of the archive — you can `DROP DATABASE` and
  rebuild it at any time.
- Case-law corpus expansion is deferred — court decisions are outside the scope of
  the primary-source archive (legalize-kr); a separate data source and license review
  would have to come first.

## MCP Server — LLM Integration

Interpreting everyday language into statutory language is what LLMs do best.
law-cli covers the other side — it ships an MCP (Model Context Protocol) server,
`law-cli-mcp`, that gives the LLM **exact article texts with primary-source URLs**.
The LLM interprets the user's phrasing and calls the search/lookup tools, so every
citation is grounded in the original text and its source.

### Install & register

```bash
# MCP server + semantic search (use "law-cli[mcp]" for lookup tools only)
uv tool install "law-cli[mcp,semantic]"

# Register with Claude Code
claude mcp add law-kr -- law-cli-mcp
```

### Using a GUI — Claude Desktop

If you'd rather not use a terminal, register the server in
[Claude Desktop](https://claude.ai/download) — the chat window becomes the GUI.
Ask in everyday language and Claude finds the articles and cites them with sources.

1. **Install** (one-time terminal step):
   ```bash
   git clone https://github.com/legalize-kr/legalize-kr.git ~/legalize-kr
   uv tool install "law-cli[mcp,semantic]"
   ```
2. **Register**: Claude Desktop → Settings → Developer → **Edit Config**, which opens
   `claude_desktop_config.json`:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

   ```json
   {
     "mcpServers": {
       "law-kr": {
         "command": "law-cli-mcp",
         "env": { "LEGALIZE_KR_REPO": "/Users/me/legalize-kr" }
       }
     }
   }
   ```
3. **Restart and verify**: the `law-kr` server should appear under the tools icon
   in the chat input.
4. **Use it** — just ask:
   > "My landlord won't return my jeonse deposit. Which laws apply?"
   > "What did Article 18 of the Stalking Punishment Act say as of June 2023?"

The lookup tools (article text, TOC, law-name search) work without PostgreSQL —
only `semantic_search` needs the PostgreSQL + pgvector setup above; without it,
Claude falls back to keyword search.

Point `LEGALIZE_KR_REPO` at the archive (falls back to conventional paths).

### Tools

| Tool | Role |
|------|------|
| `lookup_article` | Full article text by law name + article number (supports `as_of`) |
| `list_law_articles` | Table of articles for a law |
| `search_laws` | Find law names by keyword |
| `semantic_search` | Natural-language hybrid search (scoped by preset/law_filter) |

`semantic_search` requires PostgreSQL + pgvector (see "Setup" above). Every result
carries the source URL and a reference-only disclaimer, and the server instructions
tell the LLM to always present the source alongside any citation.

## Locating the Archive

The `legalize-kr` archive is auto-detected in this order:

1. the `--repo <path>` option
2. the `LEGALIZE_KR_REPO` environment variable
3. `./legalize-kr` → `~/legalize-kr`

## Disclaimer

- This tool is **not legal advice.** The output is for reference only — always verify
  against the original text at the source URL.
- The archive is generated from the open-data API; there can be a delay between
  promulgation and its appearance in the archive.

## Development

```bash
uv sync
uv run pytest
```

## License

MIT

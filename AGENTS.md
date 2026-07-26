# AGENTS.md

> Operational contract for coding agents working on **ccgp-collect**.
> Authoritative long-form docs: [README.md](./README.md), [docs/technical.md](./docs/technical.md), [流程.md](./%E6%B5%81%E7%A8%8B.md).
> When this file conflicts with those, the long-form docs win on details; this file wins on workflow.

---

## 1. What this repo is

A targeted crawler for public tender announcements on `ccgp.gov.cn` (China Government Procurement).

Pipeline (see [src/ccgp/main.py](./src/ccgp/main.py)):

1. **Discover** candidates
   - Default: keyword pre-filter via `search.ccgp.gov.cn/bxsearch`.
   - Fallback: legacy list pages under `www.ccgp.gov.cn/cggg/{dfgg,zygg}/gkzb/index.htm`.
   - Fallback is triggered automatically on `SearchNetworkError`; **do not remove this branch**.
2. **Parse detail pages** ([src/ccgp/parse_detail.py](./src/ccgp/parse_detail.py)) into structured fields.
3. **Two-stage filter**
   - Round 1: `keyword_hit(...)` using `FILTER_KEYWORDS` / `FILTER_EXCLUDE_KEYWORDS`.
   - Round 2: LLM semantic filter `llm_second_filter_by_combined(...)`.
4. **Optional attachments**: download + extract text (`pdf/docx/xlsx/txt/zip`).
5. **Optional LLM summaries**: `requirement_brief`, `requirement_desc`.
6. **Persist** to [src/ccgp/data/tender_items.csv](./src/ccgp/data/tender_items.csv); write per-run `filter_trace_*.csv` and rolling logs.
7. **Post-process** via `clean_tender_items()` (see [src/ccgp/data/clean_tender_items.py](./src/ccgp/data/clean_tender_items.py)) → produces `src/ccgp/data/cleaned_requirements.csv` (gitignored). Rich-text HTML output is off by default (`CCGP_ENABLE_RICH_TEXT`).
8. **Cleanup** old attachment folders (`_YYYYMMDD` suffix) beyond `CLEAN_THRESHOLD` days.

Scheduled runs and Pages deploy live in [.github/workflows/weekly.yml](./.github/workflows/weekly.yml) (daily 04:00 CST, Python 3.11 on `ubuntu-latest`, auto-commits the CSV, uploads `logs/` and `filter_trace/` as artifacts) and [.github/workflows/pages.yml](./.github/workflows/pages.yml) (triggered on `docs/**` / CSV changes and on successful Daily Run).

---

## 2. Map of the codebase

| Area | Path |
| --- | --- |
| CLI entrypoint (both modes + cleanup) | [src/ccgp_collect.py](./src/ccgp_collect.py) |
| Core pipeline + CLI flags | [src/ccgp/main.py](./src/ccgp/main.py) |
| List / search page parsing | [src/ccgp/parse_index.py](./src/ccgp/parse_index.py) |
| Detail page parsing | [src/ccgp/parse_detail.py](./src/ccgp/parse_detail.py) |
| HTTP, attachments, CSV, time utils | [src/ccgp/tools.py](./src/ccgp/tools.py) |
| Global config & env knobs | [src/ccgp/config.py](./src/ccgp/config.py) |
| `TenderItem` dataclass (CSV schema) | [src/ccgp/model.py](./src/ccgp/model.py) |
| LLM providers, 2nd-round filter, summaries | [src/ccgp/llm_requirements.py](./src/ccgp/llm_requirements.py) |
| Post-processing / rich-text / budget recheck | [src/ccgp/data/clean_tender_items.py](./src/ccgp/data/clean_tender_items.py), [src/ccgp/data/recheck_budgets.py](./src/ccgp/data/recheck_budgets.py), [src/ccgp/data/excel_rich_text_processing.py](./src/ccgp/data/excel_rich_text_processing.py) |
| Logger | [src/utils/mylogger.py](./src/utils/mylogger.py) |
| Runtime output (generated, do not edit) | `src/ccgp/data/tender_items.csv`, `src/ccgp/data/logs/`, `src/ccgp/data/attachments/`, `src/ccgp/data/filter_trace/` |
| Static dashboard | [docs/index.html](./docs/index.html), [docs/assets/app.js](./docs/assets/app.js), [docs/assets/style.css](./docs/assets/style.css) |
| Dependencies | [requirements.txt](./requirements.txt) |

---

## 3. Environment & commands

- Python 3.10+ locally; **CI pins Python 3.11** (see [.github/workflows/weekly.yml](./.github/workflows/weekly.yml)). Don't rely on syntax newer than 3.11.
- Code should stay cross-platform (Windows / Linux / macOS) because GitHub Actions runs it on `ubuntu-latest`.
- **Primary dev platform is Windows.** Prefer **PowerShell 5** or **Git Bash (Git for Windows)** when proposing terminal commands; avoid shell features that only exist in `bash 4+` / `zsh` unless the user asks.
  - PowerShell 5 note: chain commands with `;`, not `&&` (only PS 7+ supports `&&`).
- Before running any command, ensure the project's Python environment (venv / conda / etc.) is active. Activation details vary per machine — ask the user if unsure instead of guessing a path.

Common commands (run from repo root; syntax works in both PowerShell 5 and Git Bash):

```bash
# Recommended run: search pre-filter with auto-fallback
python src/ccgp_collect.py --days 1

# Force legacy list-page mode
python src/ccgp_collect.py --no-search --days 3

# Install deps
pip install -r requirements.txt

# Quick static check for a changed module
python -m py_compile src/ccgp/main.py
```

Runtime env vars (full list in [docs/technical.md](./docs/technical.md)):

- LLM keys (at least one): `MOONSHOT_API_KEY`, `VOLC_API_KEY`, `DEEPSEEK_API_KEY`.
- Feature toggles: `CCGP_ENABLE_ATTACHMENTS`, `CCGP_ENABLE_LLM`, `CCGP_ENABLE_RICH_TEXT`.
- Tuning: `CCGP_HTTP_TIMEOUT`, `CCGP_DOWNLOAD_TIMEOUT`, `CCGP_MAX_ATTACHMENTS`, `CCGP_SLEEP_MIN`, `CCGP_SLEEP_MAX`, `CCGP_SKIP_REPEAT_FAILED_ATTACHMENTS`.
- Geocoding: `AMAP_GEOCODING_KEY`.

---

## 4. Conventions the agent must follow

**Code style**

- Read the file first, edit second. Never write with stale content.
- Keep comments minimal; prefer descriptive names.
- Centralise config in [src/ccgp/config.py](./src/ccgp/config.py). New knobs should be env-overridable via `_env_bool` / `_env_int` / `_env_float` so CI can toggle them.
- Extend `FIELD_ALIASES` in [src/ccgp/config.py](./src/ccgp/config.py) before adding branching logic in [src/ccgp/parse_detail.py](./src/ccgp/parse_detail.py).
- Log via `get_logger()` from [src/utils/mylogger.py](./src/utils/mylogger.py). Use `print` only for entrypoint progress in [src/ccgp_collect.py](./src/ccgp_collect.py).

**Schema stability**

- CSV column order comes directly from the field order of `TenderItem` in [src/ccgp/model.py](./src/ccgp/model.py) — treat that dataclass as the source of truth. [README.md](./README.md) intentionally omits the field list to keep the public description minimal; the exhaustive field table lives in [docs/technical.md](./docs/technical.md). When you edit fields, align `TenderItem`, the CSV writer in [src/ccgp/main.py](./src/ccgp/main.py), the field table in [docs/technical.md](./docs/technical.md), and the dashboard columns in [docs/assets/app.js](./docs/assets/app.js) in a single change.

**Politeness to remote services**

- Respect existing sleeps, blocklists, and dedup logic in [src/ccgp/main.py](./src/ccgp/main.py) and `ATTACHMENT_BLOCKLIST_*` in [src/ccgp/config.py](./src/ccgp/config.py).
- The user has explicitly asked to **minimise traffic to slow endpoints like Hugging Face**. During development prefer `CCGP_ENABLE_LLM=false` and small samples (`--days 1`).
- Keep the `SearchNetworkError` → legacy-list-page fallback intact; CI depends on it.

**Traceability**

- Every candidate must produce a row in `filter_trace_*.csv` with `title`, `url`, `is_selected`, `not_selected_reason`. Do not drop this when refactoring the main loop.

**Communication**

- The user prefers **Chinese** for chat replies, PR reviews, and summaries. This file is English on purpose (denser for LLM parsing); reply to the user in Chinese.

---

## 5. Hard "don'ts"

1. Don't create new `*.md` / README / example files unless the user asks.
2. Don't commit secrets. `.env` and everything under `docs/data/` are gitignored — keep it that way.
3. Don't hand-edit generated artefacts: `src/ccgp/data/tender_items.csv`, `logs/`, `attachments/`, `filter_trace/`. `weekly.yml` auto-commits the CSV.
4. Don't remove the search-mode auto-fallback.
5. Don't run `git commit` / `git push` without an explicit user request.
6. Don't weaken or delete tests / assertions to make a task "pass". If a test looks wrong, explain why first.
7. Don't hardcode absolute local paths in code or docs — use repo-relative paths.

---

## 6. Recipes

**Add a keyword / exclude word** — edit `FILTER_KEYWORDS` / `FILTER_EXCLUDE_KEYWORDS` in [src/ccgp/config.py](./src/ccgp/config.py). Broad tokens like `智能` / `智慧` are intentionally placed late so search pre-filter throttling hits them last.

**Add a structured field**
1. Add attribute on `TenderItem` in [src/ccgp/model.py](./src/ccgp/model.py).
2. Extract it in [src/ccgp/parse_detail.py](./src/ccgp/parse_detail.py); extend `FIELD_ALIASES` if needed.
3. Wire it into the CSV row in [src/ccgp/main.py](./src/ccgp/main.py).
4. Update the field table in [docs/technical.md](./docs/technical.md) and the dashboard column set in [docs/assets/app.js](./docs/assets/app.js). ([README.md](./README.md) no longer maintains the field list — do **not** add it back there.)

**Tune attachment behaviour** — adjust `ATTACHMENT_BLOCKLIST_HOSTS`, `ATTACHMENT_BLOCKLIST_KEYWORDS`, `MAX_ATTACHMENTS_PER_NOTICE` in [src/ccgp/config.py](./src/ccgp/config.py), or the download / extract helpers in [src/ccgp/tools.py](./src/ccgp/tools.py).

**Swap / add an LLM provider** — change the provider chain in [src/ccgp/llm_requirements.py](./src/ccgp/llm_requirements.py) and reflect the priority table in [docs/technical.md](./docs/technical.md).

**Debug CI** — inspect [.github/workflows/weekly.yml](./.github/workflows/weekly.yml) and [.github/workflows/pages.yml](./.github/workflows/pages.yml). "Fast mode" recipe: `CCGP_ENABLE_LLM=false`, tighter `CCGP_SLEEP_*`, smaller `CCGP_MAX_ATTACHMENTS`. When a CI run misbehaves, first pull the `ccgp-logs-*` and `ccgp-filter-trace-*` artifacts uploaded by the Daily Run.

**Re-run data post-processing** — [src/ccgp/data/clean_tender_items.py](./src/ccgp/data/clean_tender_items.py) regenerates `cleaned_requirements.csv` from the raw `tender_items.csv`; [src/ccgp/data/recheck_budgets.py](./src/ccgp/data/recheck_budgets.py) re-parses the `budget` column for rows that failed extraction. Both are safe to re-run without touching the crawler.

**Preview the dashboard locally**

Git Bash:

```bash
mkdir -p docs/data
cp src/ccgp/data/tender_items.csv docs/data/tender_items.csv
python -m http.server 8080 --directory docs
```

PowerShell 5:

```powershell
New-Item -ItemType Directory -Force -Path docs/data | Out-Null
Copy-Item src/ccgp/data/tender_items.csv docs/data/tender_items.csv -Force
python -m http.server 8080 --directory docs
```

---

## 7. Definition of done

Before returning to the user, verify:

- [ ] Files were re-read immediately before Edit / Write.
- [ ] No new stray docs or committed secrets; no absolute local paths in new content.
- [ ] `TenderItem` ↔ CSV row ↔ field table in [docs/technical.md](./docs/technical.md) ↔ [docs/assets/app.js](./docs/assets/app.js) stay in sync (do not re-add field list to [README.md](./README.md)).
- [ ] `GetDiagnostics` clean, or `python -m py_compile` on touched modules, or a `--days 1` smoke run.
- [ ] Search → list-page fallback and `filter_trace_*.csv` writes still present.
- [ ] Reply to the user in Chinese.

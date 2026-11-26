# AGENTS.md - Trader-Skill-ID

Reply to the user in English. Keep answers short and concrete.

## Project
Agent-skill pack for Google Antigravity for day-trading ANALYSIS: US stocks, Indonesian stocks (IDX/BEI) and forex.
Started from Jakeschincariol/day-trader-skill (MIT, upstream commit 3d0f4ef). Git remote `upstream` points there: fetch only, never push.

- Each skill = `skills/<name>/SKILL.md` + one standard-library Python script.
  (Before task P02 the folders are still `trader-*/` at the repo root.)
- Shared market code + market profiles: `skills/trader-core/` (`market.py`, `markets/*.json`), from task P03a on.
- Skills hand work to each other through files in `trader/` inside the user's CURRENT folder (gitignored).
- Pipeline: scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker; alerts while a trade is open; news / analyst / pelosi on a schedule.
- Tests: `tests/` (unittest, offline fixtures in `tests/fixtures/`).

## Hard rules
- Standard library only, Python 3.8 compatible (no zoneinfo, no `match`, no `list[...]` hints); tests/test_repo.py enforces it. No new dependencies.
- No skill may place an order by itself. Paper / manual journal is the default. Never weaken: `require_stop`, the explicit per-order "yes", the risk PASS fingerprint, `allow_short` / `allow_margin` / `allow_options` default false.
- Every SKILL.md on the order path keeps the sentence "Not financial advice".
- Never commit `trader/`, `data/`, `.env`, API keys or personal emails. Never ask for, print or read back keys.
- Tests run OFFLINE. Never let a test hit the network. New fixtures are cut from real data, kept small (gzip above 200 KB), with source + date noted in the test.
- Free data endpoints: keep the polite pause and the single 429 retry. Never add code that bypasses bot protection (Cloudflare, captchas). If an official site blocks automated access, read a file the user downloads by hand instead.
- Market rules (hours, holidays, tick size, lot, auto-rejection limits, fees) live in `markets/*.json`, never hard-coded in a skill script (from P03a on). Every rule value carries a source URL and a "checked" date.
- US behaviour must not change unless the task says so: existing US tests keep passing without edits to their assertions.
- Text in this repo uses plain "-" (no em dash character); tests check it.
- The user runs Windows + PowerShell. Docs and printed commands use `python`, PowerShell syntax and `\` paths where a path is typed by the user.
- One git command per terminal call; no `;`, `&&` or Write-Host chaining.

## Check
- From P01 on: `.\check.bat nopause` (unittest + compileall, prints PASS/FAIL). Never run plain `check.bat` in the agent shell: it waits for a key press.
- Before P01: `python -m unittest discover -s tests`.

## Code navigation
Use codegraph (explore / callers) to find every caller of a function or constant before you rename, move or delete it.

## Git & Commit
- Before each commit: run the check, `git status`, `git diff`; run skill ponytail-review on the change; fix Bug/Risk findings, only report Speed/Lean ones.
- Stage only this task's files (`git add <files>`). Conventional Commits in English, max 72 chars, one concern per commit. Never `--no-verify`.
- No push unless the user asks. Never push to `upstream`.
- If git fails with "must be run in a work tree", rerun the same command outside the sandbox. To search, use `git grep --no-index --exclude-standard -n "<text>"`.
- This project has NO .venv (standard library only): run `python`, never `.venv\Scripts\python.exe`. The warning "Failed to find real location of ...python.exe" is harmless; read the test result below it.

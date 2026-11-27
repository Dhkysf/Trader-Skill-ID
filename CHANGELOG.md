# Changelog

All notable changes to Trader Skill ID are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-11-27

### Added
- Antigravity plugin manifest (`.antigravity-plugin/plugin.json`), `skills/` layout, `check.bat`, and `AGENTS.md`.
- `trader-core` market profile engine (`market.py`, `markets/idx.json`, `markets/fx.json`) for sessions, holidays, DST, overnight sessions, tick tables, ARA/ARB bands, and market capabilities.
- Full Indonesian stock (IDX/BEI) support across all 9 skills: Daftar Saham universe, Indonesian RSS news feeds, WIB sessions with lunch-break handling, 10-minute Yahoo delay notice, 100-share lots and broker fees, ARA/ARB checks, manual tickets, and offline IDX fixtures/tests.
- Full 24/5 spot forex support across the pipeline (`fx.json`, `config.fx.example.json`): London/NY ORB long and short scans, short entries and exits in pips, 0.01-lot and leverage/spread sizing, forex risk checks, manual forex tickets, 24-hour Time Machine replays, and offline forex fixtures/tests.
- Indonesian main `README.md` with plain-language glossary, `README.en.md`, and bilingual EN/ID triggers in every `SKILL.md`.

### Changed
- Rebranded from upstream `day-trader-skill` (commit `3d0f4ef`) to `Trader Skill ID` and ported `SKILL.md` files to Google Antigravity.
- Made `idx` the default market profile and unified currency-neutral money limits.
- Polished forex wording in script outputs (`Risk per unit`, `BEFORE you enter`, `close below a level`) without altering IDX output.

### Fixed
- Polite single-429 retry rule across all network calls.
- Stricter per-order `"yes"` parsing, risk PASS fingerprint covering market and stop, and buy/sell fee accounting in budget and portfolio fills.
- Holiday, calendar-year, and missing ARA/ARB rule checks without crashing.

### Removed
- US stock market profile, US-only tests/fixtures, and US-only `trader-analyst` and `trader-pelosi` skills.

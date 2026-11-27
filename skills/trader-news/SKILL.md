---
name: trader-news
description: >-
  News Monitor. Tracks breaking news on every stock you watch and flags what
  moves it: Yahoo Finance headlines per ticker, Indonesian financial RSS feeds, and how
  far each stock is from yesterday's close. Shows only what is new since the
  last check, newest first, in WIB, tags each item (earnings,
  analyst, deal, halt, regulatory, macro...) and never repeats one. Use when
  the user says "any news on BBCA", "why is this moving", "what's the news on
  my watchlist", "morning briefing", "pre-market news", "monitor the news",
  "did anything break", or after /trader-scanner finds setups.
argument-hint: "[tickers]"
---

# trader-news

A chart can look perfect and still be about to gap on an earnings date, a
halt or a lawsuit. Before a setup becomes a trade, this skill reads the two
feeds that carry those first, for every stock on the watchlist, and tells you
only what is new. It also prints how far each stock has moved today, so a
headline and a move sit side by side.

`<skill-dir>` is the folder that holds this SKILL.md (`skills/trader-news` in this repo, `.agents/skills/trader-news` in a workspace). Commands below use `python` (use `python3` on macOS/Linux).

```bash
python "<skill-dir>/news.py"                         # watchlist + plan + portfolio
python "<skill-dir>/news.py" --tickers BBCA BBRI --hours 12
python "<skill-dir>/news.py" --json
```

## What it reads and writes

| file / feed | what |
| --- | --- |
| `--tickers`, else `trader/watchlist.json` | the scanner's hits (trader-scanner) |
| `trader/plan.json` | the trade you are planning (trader-exit) |
| `trader/portfolio.json` | what you hold (trader-broker records fills there) |
| `news_feeds` in `trader/config.json` | Indonesian financial RSS feeds (`label`, `url`) |
| Yahoo Finance chart endpoint | the last price against yesterday's close (`.JK` suffix, unofficial, can lag) |
| `trader/state/news.json` | what has been shown (kept 30 days) |

## The rules

- **Headlines are leads, not facts.** Before telling the user something
  happened, open the story and read it. Quote the source and link it. Never
  summarise a paywalled story you could not read: say so.
- **Say what it touches.** Every item lists the tickers it touches and its
  tags: earnings, analyst, legal, deal, capital, people, risk, halt,
  regulatory, macro.
- **MOVING** marks a stock 3 % or more from yesterday's close (`--move-pct`).
  A move with no headline is worth saying out loud too.
- **No predictions.** Report what was published and how far the price is from
  yesterday's close. Never say what the stock will do next.

## Steps

1. Run the check: `python "<skill-dir>/news.py"`. Exit code 1 means
   nothing new. `--all` shows items already seen, `--json` gives everything
   machine readable, `--dry-run` leaves the state alone.
2. Read the items that matter: anything tagged earnings, halt, legal,
   regulatory or risk, and every MOVING ticker first.
3. Write a short brief, per ticker: what happened, the source and link, the
   move, and one line on why it matters to the setup (for example "earnings
   are this week: an overnight gap can jump past any stop").
4. If a story changes the picture, say so before `/trader-entry` and
   `/trader-exit`: an earnings date inside the trade, a halt, an offering.
   Never act on a headline alone.

During the session: `/loop 15m /trader-news`, or a scheduled task each
morning before the open.

## Example

Monday 2026-11-23, BBCA broke its opening range at 09:35 WIB. The check at
09:52 WIB reads the configured Indonesian RSS feeds and Yahoo Finance `.JK`
price: `BBCA Rp 9.875 +1.80% vs yesterday's close Rp 9.700 at 09:52 WIB  MOVING`.
When a ticker has no news, say so rather than padding the brief.

## What it never does

- Never invents or embellishes a story, a quote or a number.
- Never trades on news, and never tells the user to buy or sell because of a
  headline.
- Never hammers a server: one request per feed, a polite pause between calls.

## IDX (Indonesian stocks, default)

When `"market"` is `"idx"` (the default when omitted in `trader/config.json`):

- Reads RSS feeds from `news_feeds` (`label`, `url`) in `trader/config.json` (see `skills/trader-budget/config.example.json`).
- Matches items to watched tickers by stock code and by company name from `trader/universe.txt` (`SYMBOL|Name`, `--universe`), ignoring unrelated items.
- Checks the price move via Yahoo Finance chart (`.JK` suffix) and prints times in `WIB` and prices in `Rp`.
- Offline mode reads cached RSS fixtures without hitting the network.

## Safety

Education and tooling, not financial advice. This skill only reads and
reports. Nothing places an order except `/trader-broker`, after
`/trader-risk` passes and the user types an explicit yes for that order.

# Trader Skill ID

Agent skills for day-trading analysis in Google Antigravity: Indonesian stocks (IDX) today, forex next.

Free, MIT, no signup, no API key. The tools are plain Python that read free
public data: Yahoo Finance charts and Indonesian RSS news feeds.

One scans thousands of charts for setups. Another tracks breaking news on
every stock you watch. One watches a setup bar by bar and tells you the moment
to get in, and another sets your stop and your target before you do. And the
craziest one is the Time Machine: before you risk any money, it replays the
rest of the session 10,000 times from the stock's own recent bars, plus every
past day the same setup fired, and tells you the honest odds.

And no trade goes through until you say yes. Nothing in this pack can place
an order on its own. Paper trading is the default.

## Install

**(a) Recommended: a dedicated trading folder (Antigravity IDE)**

The skills write working files (`watchlist.json`, `plan.json`, `orders.json`, `state/`) into `trader\` inside your current folder. Using a dedicated folder keeps trading state out of your code repos.

In PowerShell, copy the skills into your trading folder's `.agents\skills\` directory:

```powershell
New-Item -ItemType Directory -Force -Path "E:\Projects\Trading-Lab\.agents\skills"
Copy-Item -Recurse -Force ".\skills\trader-*" "E:\Projects\Trading-Lab\.agents\skills\"
```

(Use any dedicated folder path you prefer.) Open that folder in Google Antigravity, start a new chat, and run `/trader-news BBCA`.

**(b) Antigravity CLI (`agy`)**

```powershell
agy plugin install https://github.com/Dhkysf/Trader-Skill-ID
```

The tools need Python 3.8 or newer. Nothing to pip install.

## The nine

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans thousands of charts for setups: opening-range breakouts, flags, oversold bounces. |
| `/trader-news` | News Monitor | Tracks breaking news on every stock you watch and flags what moves it. |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and your target before you enter, so you know when to get out. |
| `/trader-timemachine` | Time Machine | Replays every possible outcome of a trade before you risk money: 10,000 simulated sessions plus every past time the setup fired. |
| `/trader-risk` | Risk Manager | Checks every trade against your limits and stops anything over them. |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and your max loss per trade. |
| `/trader-broker` | Order Executor | Renders manual order tickets and logs your explicit yes and fills, never without your yes. |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop or the opening bell hits. |

Shared module: `/trader-core` - shared market rules used by the other skills.

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by the close                                       (while it is open)
news                                                                           (on a schedule)
```

An example on IDX: BBCA, Monday November 23 2026, real data (WIB).

1. **`/trader-scanner`** at 09:35 WIB: BBCA closed above its 15-minute opening
   range (09:00-09:15, Rp 5.425 to Rp 5.500): the 09:30 candle closed at
   Rp 5.550 (+0.91%).
2. **`/trader-news`**: checks Indonesian RSS feeds (`news_feeds` in
   `trader/config.json`) for BBCA headlines in WIB and shows today's price
   move vs yesterday's close.
3. **`/trader-entry`** watches BBCA bar by bar (5-minute bars, Yahoo `.JK`
   data is about 10 minutes late) and flags the first closed bar above the
   range high.
4. **`/trader-exit`** sets the plan before the entry: stop rounded down to the
   IDX tick (e.g. Rp 9.700), target (e.g. 2R at Rp 10.200), flat by 15:45 WIB
   either way, and warns if the plan holds through the lunch break or hits
   today's ARA/ARB band.
5. **`/trader-timemachine`** replays the rest of the day 10,000 times from
   BBCA's own 5-minute bars over the previous 60 days (seed 19, separate
   Mon-Thu and Friday slot maps, lunch-gap isolation, ARA/ARB clamping) plus
   every past session the same rule fired.
6. **`/trader-budget`** with a Rp 10.000.000 account and Rp 100.000 max loss
   per trade: sizes in whole lots of 100 shares, including buy/sell broker
   fees, and writes one manual order to `trader/orders.json`.
7. **`/trader-risk`** checks it against your limits: lot size, IDX tick table,
   ARA/ARB band, lunch break, pre-closing, max loss incl. fees, daily loss,
   trades per day, reward:risk, and cash. PASS or BLOCK, with the reason.
8. **`/trader-broker`** shows you the manual ticket in plain words. You type
   yes for that exact order, enter it in your broker app yourself, and record
   the fill.
9. **`/trader-alerts`** rings on the stop, the target and at 15:45 WIB to
   flatten whatever is still open.

## The tools

All standard-library Python. The data tools read public endpoints and are
polite about it. Commands below use `python` on Windows (use `python3` and `/`
on macOS/Linux):

```powershell
python skills\trader-scanner\scan.py universe --from data\daftar-saham.csv   # IDX Daftar Saham -> trader/universe.txt
python skills\trader-scanner\scan.py daily                                   # pre-market setups, whole universe
python skills\trader-scanner\scan.py orb --at 10:15                          # opening-range breakouts so far (WIB)
python skills\trader-news\news.py --tickers BBCA --hours 12                  # RSS headlines, today's move
python skills\trader-entry\entry.py check BBCA --setup orb                   # waiting / triggered / expired
python skills\trader-entry\entry.py watch BBCA --every 30                    # bar by bar until it triggers
python skills\trader-exit\exit.py plan --stop or-mid --target 1R --write     # -> trader/plan.json
python skills\trader-timemachine\timemachine.py run --write                  # 10,000 replays + the history
python skills\trader-budget\size.py --write                                  # -> trader/orders.json
python skills\trader-risk\check.py                                           # PASS / BLOCK per order
python skills\trader-broker\ticket.py show                                   # the tickets, READY or not
python skills\trader-alerts\alerts.py add --from-plan                        # stop, target, flat by close
python skills\trader-alerts\alerts.py check                                  # rings what hit, once
```

```powershell
.\check.bat nopause
python -m unittest discover -s tests -v
```

The tests run offline, on IDX fixtures cut from real data (BBCA, BBRI, TLKM,
GOTO, and CNBC Indonesia RSS).

## Fine print

**Not financial advice.** This is software that reads public data and does
arithmetic. It does not know your situation and it cannot see the future.
Most people who day trade lose money. You can lose money. Decide for
yourself, and talk to a licensed professional if you need advice.

**No trade goes through until you say yes.** Only `/trader-broker` can lead to
an order, and only after `/trader-risk` passes that exact order and you type
yes for it in the chat. Set your brokerage order tool to `ask` in Antigravity
permissions, never `allow`, so the agent's own permission prompt is a second
check. Never use Turbo mode in a trading workspace. No options, margin, short
selling or leverage unless you turn them on.

**Paper first.** `"paper": true` and `"broker": "manual"` are the defaults in
`config.example.json`. IDX orders are entered manually in your broker app.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute bars. The future can do things those 60
days never did: an earnings report, a halt, a headline. Treat its odds as a
reality check, never as a promise.

**A stop is a plan, not a guarantee.** In a fast market or across a gap, a
stop order can fill well past its price. The max loss shown is the loss at
the stop price.

**The data is free and unofficial.** Yahoo Finance's chart endpoint is not an
official API: it can lag, change or rate-limit you. The scanner and the entry
timer read 1-minute or 5-minute bars, not every tick. Check anything that
matters against your broker before you act on it.

**Taxes.** Nothing here is tax advice.

## Files

```
.antigravity-plugin/plugin.json
skills/
  trader-core/        SKILL.md, market.py, markets/idx.json
  trader-scanner/     SKILL.md, scan.py
  trader-news/        SKILL.md, news.py
  trader-entry/       SKILL.md, entry.py
  trader-exit/        SKILL.md, exit.py
  trader-timemachine/ SKILL.md, timemachine.py
  trader-risk/        SKILL.md, check.py
  trader-budget/      SKILL.md, size.py, config.example.json, targets.example.json
  trader-broker/      SKILL.md, ticket.py
  trader-alerts/      SKILL.md, alerts.py, alerts.example.json
tests/                unittest suite + offline fixtures
```

## Credits

Based on [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT), upstream commit 3d0f4ef.

## Ringkasan (Bahasa Indonesia)

Trader Skill ID adalah paket skill agen untuk analisis day-trading di Google Antigravity: saham Indonesia (IDX) saat ini, dan forex berikutnya. Ini bukan nasihat keuangan; semua keputusan transaksi tetap di tangan Anda dan tidak ada order yang dikirim tanpa persetujuan eksplisit. Data pasar yang digunakan bersifat gratis, tidak resmi, dan dapat tertunda.

MIT.

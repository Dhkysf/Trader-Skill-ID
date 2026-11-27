# Trader Skill ID

Bahasa Indonesia: [README.md](README.md)

Agent skills for day-trading analysis in Google Antigravity for Indonesian traders: Indonesian stocks (IDX/BEI) and 24/5 spot forex.

Free, MIT, no signup, no API key. Plain standard-library Python (3.8+) reading public data: Yahoo Finance charts and Indonesian financial RSS feeds.

One skill scans thousands of charts for setups. Another tracks breaking news. One watches a setup bar by bar for the entry moment, another sets your stop and target before you enter, and the Time Machine replays the rest of the session 10,000 times from the last 60 days before you risk any money.

No order goes through until you say yes. Orders are always manual, with paper trading as the default.

## Short glossary

- **ORB (Opening-Range Breakout)**: price closing above or below the opening range (first 15 minutes by default).
- **Stop (stop-loss)**: the exit price if the setup fails, to cap your loss.
- **R**: initial risk unit per trade (1R = distance from entry to stop; 2R = twice that distance).
- **ARA/ARB**: Auto Rejection Atas / Bawah, daily upper and lower price limits on IDX stocks.
- **Pip**: smallest price increment for a forex pair (0.0001 for EURUSD; 0.01 for USDJPY; 1 for USDIDR).
- **Lot**: position size unit (100 shares on IDX; 100,000 base units in forex, minimum 0.01 lot).

## Skills per market

| Command | Job | Markets | What it does |
| --- | --- | --- | --- |
| `/trader-scanner` | Chart Scanner | IDX, Forex | Scans for daily setups and opening-range breakouts (ORB). |
| `/trader-news` | News Monitor | IDX (RSS + price), Forex (price) | Tracks Indonesian RSS headlines and daily price moves. |
| `/trader-entry` | Entry Timer | IDX, Forex | Watches bars and flags the first closed bar past the level. |
| `/trader-exit` | Exit Planner | IDX, Forex | Sets stop and target before entry, checking ticks and ARA/ARB. |
| `/trader-timemachine` | Time Machine | IDX, Forex | Runs 10,000 simulated sessions + past history over the last 60 days. |
| `/trader-budget` | Budget Manager | IDX, Forex | Sizes lots to your budget and max loss per trade. |
| `/trader-risk` | Risk Manager | IDX, Forex | Checks every order against your rules: PASS or BLOCK with reasons. |
| `/trader-broker` | Order Executor | IDX, Forex | Renders manual order tickets and logs your explicit yes and fills. |
| `/trader-alerts` | Price Alerts | IDX, Forex | Rings when a price, stop, target, opening bell, or flat-by time hits. |

Shared module: `/trader-core` - market rules, trading hours, holidays, and tick rounding from `markets/*.json`.

## Install (Google Antigravity)

**(a) Recommended: a dedicated trading folder (Antigravity IDE)**

The skills write working files (`watchlist.json`, `plan.json`, `orders.json`, `state/`) into `trader\` inside your current folder. A dedicated folder keeps trading state out of your code repos.

In PowerShell, copy the skills into your trading folder's `.agents\skills\` directory:

```powershell
New-Item -ItemType Directory -Force -Path "E:\Projects\Trading-Lab\.agents\skills"
Copy-Item -Recurse -Force ".\skills\trader-*" "E:\Projects\Trading-Lab\.agents\skills\"
```

Open that folder in Google Antigravity, start a new chat, and run `/trader-news BBCA`.

**(b) Antigravity CLI (`agy`)**

```powershell
agy plugin install https://github.com/Dhkysf/Trader-Skill-ID
```

Requires Python 3.8 or newer. Nothing to pip install.

To configure your workspace, copy an example config to `trader\config.json`:
- IDX: `skills\trader-budget\config.example.json`
- Forex: `skills\trader-budget\config.fx.example.json`

## How to use it

Everything lands in `trader\` in your workspace, and each skill reads what the last one wrote:

```text
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by the close                                       (while it is open)
news                                                                           (on a schedule)
```

Direct Python commands (Windows PowerShell; use `python3` and `/` on macOS/Linux):

```powershell
python skills\trader-scanner\scan.py universe --from data\daftar-saham.csv
python skills\trader-scanner\scan.py daily
python skills\trader-scanner\scan.py orb --at 10:15
python skills\trader-scanner\scan.py orb --session london
python skills\trader-news\news.py --tickers BBCA --hours 12
python skills\trader-entry\entry.py check BBCA --setup orb
python skills\trader-entry\entry.py watch BBCA --every 30
python skills\trader-exit\exit.py plan --stop or-mid --target 1R --write
python skills\trader-timemachine\timemachine.py run --write
python skills\trader-budget\size.py --write
python skills\trader-risk\check.py
python skills\trader-broker\ticket.py show
python skills\trader-alerts\alerts.py add --from-plan
python skills\trader-alerts\alerts.py check
```

Run the offline test suite:

```powershell
.\check.bat nopause
python -m unittest discover -s tests -v
```

## Data and delay

- **IDX stocks (Yahoo Finance `.JK`)**: delayed by about 10 minutes.
- **Forex (Yahoo Finance `=X`)**: real-time (0-minute delay).
- **Free and unofficial**: Yahoo Finance's chart endpoint is not an official API; it can lag, change, or rate-limit you. Always verify prices in your broker app before acting.

## Changing rules

Market rules live in `skills\trader-core\markets\`, never hardcoded in scripts:

- **IDX ARA/ARB bands**: in `skills\trader-core\markets\idx.json`, the current rule is valid until `valid_until` (`2026-12-31`, Peraturan II-A, Kep-00158/BEI/10-2026). Update `auto_rejection` when IDX changes the rule.
- **Yearly IDX holidays**: update `holidays` and `calendar_years` (`[2026]`) in `skills\trader-core\markets\idx.json` each year.
- **Forex profile**: update supported pairs, default spreads, and DST rules in `skills\trader-core\markets\fx.json`.

## Fine print

**Not financial advice.** This software reads public data and does arithmetic. It does not know your situation and cannot predict the future. Most people who day trade lose money. You can lose money. Decide for yourself, and consult a licensed professional if you need advice.

**No trade goes through until you say yes.** Only `/trader-broker` prepares order tickets, and only after `/trader-risk` passes that exact order and you type `yes` for it in the chat. Orders are always manual: you enter them in your broker app or platform yourself. Set any brokerage tool permission to `ask` in Antigravity, never `allow`, and never use Turbo mode in a trading workspace.

**Paper first.** `"paper": true` and `"broker": "manual"` are the defaults in both `config.example.json` and `config.fx.example.json`.

**Forex only with a Bappebti-licensed broker.** For forex trading in Indonesia, use only a broker licensed and supervised by Bappebti (check the official Bappebti list before depositing).

**The Time Machine is a simulation, not a prediction.** It is built from the last 60 days of 5-minute bars. The future can bring earnings, halts, or headlines those 60 days never saw.

**A stop is a plan, not a guarantee.** In a fast market or across a gap (including the IDX lunch break), a stop can fill worse than its price.

**Taxes.** Nothing here is tax advice.

## Credits

Based on [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT), upstream commit 3d0f4ef.

## License

MIT.

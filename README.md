
# MLB Trading Desk

A local Streamlit dashboard that pulls live game information from MLB's Stats API and turns it into a transparent live-game decision aid.

## What it currently tracks

- Live score and inning
- Pitch count
- Strikes and strike percentage
- Strikeouts and walks
- Hits, earned runs, and home runs
- Pitch velocity
- Exit velocity
- Hard-hit balls, defined as 95+ mph
- A clearly labeled barrel proxy
- Manual sportsbook moneyline input
- No-vig probability
- Manual model probability and fair moneyline
- A transparent 0–100 live pitcher score

## Installation

1. Install Python 3.11 or newer.
2. Open Terminal or PowerShell in this folder.
3. Create a virtual environment:

```bash
python -m venv .venv
```

4. Activate it.

macOS/Linux:

```bash
source .venv/bin/activate
```

Windows:

```powershell
.venv\Scripts\activate
```

5. Install dependencies:

```bash
pip install -r requirements.txt
```

6. Run the dashboard:

```bash
streamlit run app.py
```

## Important limitations

- MLB's Stats API is reachable publicly but is not presented as a fully supported consumer API.
- Live-feed fields can change.
- The "barrel proxy" is not MLB's official barrel classification.
- DraftKings does not provide a simple free public API for this use case, so odds are entered manually.
- Polymarket integration should be added only after reviewing its current official API documentation and market-resolution rules.
- This tool does not guarantee profitable betting outcomes.

## Next model upgrades

1. Store snapshots every inning in SQLite.
2. Add bullpen workload from the prior three days.
3. Add expected run expectancy by base-out state.
4. Add handedness and lineup splits.
5. Calibrate the score against historical live-game outcomes.
6. Add a bet journal with closing-line value and realized ROI.

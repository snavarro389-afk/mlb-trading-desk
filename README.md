# MLB Trading Desk

A Streamlit decision-support dashboard for MLB betting research and live-game monitoring.

## Current version: v0.2 workflow foundation

The app is organized into four workspaces:

- **Home:** Full MLB slate for the selected date
- **Pregame:** Research checklist and BET / WATCH / PASS classification
- **Live:** Existing pitch-level dashboard, contact quality, and market comparison
- **Journal:** Session-based wager and tracked-pass journal with CSV export

The workflow is intended for every MLB game day, including weekends. Postseason-specific logic will be added later.

## Installation

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Run:

```bash
streamlit run app.py
```

## Important limitations

- The live pitcher score remains a transparent heuristic, not a calibrated predictive model.
- Journal entries are stored only in the active Streamlit session; download the CSV before the session resets.
- Odds remain manual.
- The barrel proxy is not MLB's official barrel classification.
- MLB live-feed fields can change.
- This tool does not guarantee profitable betting outcomes.

## Next logical upgrades

1. Persist the journal using SQLite or a cloud data store.
2. Move scoring weights fully into `model_config.json`.
3. Add bullpen usage from the prior three days.
4. Add official lineup and handedness data.
5. Add historical calibration and closing-line-value tracking.

# Engineering Roadmap

This document connects research and betting decisions to code changes.

## Workspace roles

- **Deep Dive thread:** research, definitions, testing, and model challenges
- **Betting Strategy thread:** daily decisions, pricing, watch conditions, and operating rules
- **Engineering thread:** GitHub, Streamlit, implementation, testing, and deployment
- **GitHub:** permanent system of record
- **Streamlit:** user-facing decision dashboard

## Delivery flow

1. Research identifies a possible signal.
2. Betting Strategy defines how the signal changes a decision.
3. Engineering translates the rule into code or configuration.
4. GitHub stores the change and its history.
5. Streamlit displays the feature.
6. The bet journal measures whether it added value.

## Version plan

### v0.1 — Current foundation

- MLB schedule and live feed
- Pitching line
- Command and velocity summary
- Contact-quality summary
- Manual moneyline input
- No-vig calculation
- Manual fair-price estimate
- Heuristic live pitcher score

### v0.2 — Workflow structure

- Pregame, Live, and Journal navigation
- Visible BET / WATCH / PASS classification
- Methodology and limitation panels
- Config-driven score weights

### v0.3 — Pregame data

- Probable starters
- Recent starter form
- Handedness splits
- Official lineups
- Bullpen usage for the prior three days

### v0.4 — Market module

- Opening and current line tracking
- F5 and full-game comparison
- Price history
- Expected-value calculation
- Manual Polymarket comparison

### v0.5 — Journal and calibration

- Bet journal
- Closing-line value
- ROI by market type
- Model prediction snapshots
- Historical calibration dataset

## Immediate next build

The next app change should be small and visible:

1. Add navigation for **Pregame**, **Live**, and **Journal**.
2. Preserve the existing dashboard under **Live**.
3. Add a simple Pregame checklist.
4. Add a blank journal table or CSV-backed entry form.
5. Move score weights from hard-coded values toward `model_config.json`.

## Change-control rule

Do not add many external data sources at once. Each new source should have:

- A documented purpose
- Error handling
- A fallback state
- A visible timestamp
- A clear effect on the decision process

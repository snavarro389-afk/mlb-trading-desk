# MLB Trading Desk

## Version: v0.3 — Automated Slate Engine, Phase 1

MLB Trading Desk is a Streamlit decision-support app that reduces the daily MLB slate into a smaller set of research candidates, price checks, live watches, data checks, and passes.

The app performs repetitive data gathering and transparent comparisons. It does not place wagers and its Research Priority Score is not a projected win probability.

## Workspaces

- **Dashboard:** High-level view of the strongest attention candidates.
- **Slate:** Ranked table for every game on the selected date.
- **Game Card:** Starter and offense comparisons, data completeness, manual odds, no-vig math, and a Strategy Packet.
- **Live Desk:** Live score, inning, pitching line, command, velocity, and contact quality.
- **Journal:** Session-based decision and wager log with CSV export.

## Phase 1 automation

The app now retrieves and processes:

- Full MLB schedule for the selected date
- Probable starting pitchers
- Starting-pitcher season statistics
- Team season hitting statistics
- Transparent starter and offense component scores
- Research Priority Score
- Data-confidence classification
- Slate ranking
- Manual two-sided sportsbook odds
- No-vig probabilities and market hold
- Downloadable Strategy Packet for the Betting Strategy thread
- Existing MLB live-feed data

## Classification labels

- **DEEP DIVE:** Large measurable separation with adequate data
- **PRICE CHECK:** Worth evaluating against sportsbook pricing
- **LIVE WATCH:** Potentially useful, but better suited for live confirmation
- **DATA CHECK:** Missing or incomplete inputs prevent a confident ranking
- **PASS:** Limited measurable separation at the current stage

## Important interpretation

The Research Priority Score answers:

> Which games deserve attention?

It does not answer:

> What is the exact probability that a team wins?

Starting pitching currently receives 65% of the matchup comparison and team offense receives 35%. These are initial transparent research weights, not a validated predictive model.

## Installation

1. Install Python 3.11 or newer.
2. Install dependencies:

```bash
pip install streamlit pandas requests
```

3. Run:

```bash
streamlit run app.py
```

## Current limitations

- DraftKings and other sportsbook odds remain manual.
- Confirmed lineups are not integrated yet.
- Bullpen workload is not integrated yet.
- Injury and late-scratch context is not integrated yet.
- Team offense is season-level in Phase 1; handedness and recent-form splits come later.
- MLB Stats API fields can change.
- Journal entries remain session-based.
- The barrel indicator in the Live Desk is a proxy, not MLB's official barrel classification.
- The system does not guarantee profitable betting outcomes.

## Next build phases

### Phase 2 — Bullpen and lineup intelligence

- Prior three days of reliever usage
- High-leverage reliever availability
- Confirmed lineup status
- Starter handedness matchup
- Lineup-change detection
- Improved data-confidence calculation

### Phase 3 — Market layer

- Saved odds by game
- Fair-price comparison
- Target-price logic
- F5 versus full-game market comparison
- Reclassification after market entry

### Phase 4 — Live thesis engine

- Save the pregame thesis
- Trigger-by-trigger live monitoring
- Velocity baseline comparison
- Strike-rate, walk, pitch-count, and hard-contact thresholds
- Thesis status: Confirmed, Continue Watching, or Cancel

### Phase 5 — Persistence and validation

- SQLite or cloud storage
- Closing-line-value tracking
- Component-level performance analysis
- Historical calibration
- Weight adjustment based on evidence

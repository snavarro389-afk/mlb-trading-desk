# MLB Trading Desk

## Version: v0.4 — Matchup Intelligence

This release moves the app beyond season-only comparisons.

## New automation

- Probable starter throwing hand
- Team offense versus right-handed or left-handed pitching
- Matchup-adjusted offense score
- Team offense context over the last 14 and 30 days
- Starter recent-30-day context
- Lineup readiness using MLB boxscore batting-order availability
- Readiness labels:
  - `READY FOR PRICE`
  - `AWAIT LINEUPS`
  - `PARTIAL LINEUPS`
  - `DATA CHECK`

## Scoring behavior

The offense matchup score uses:

- 55% season offense baseline
- 45% offense versus the opposing starter's handedness

Recent 14- and 30-day performance is shown as context and is not yet heavily weighted into the separation score.

## Interpretation

The app now answers:

1. Which games show meaningful baseball separation?
2. Is that separation supported by the handedness matchup?
3. Is recent form reinforcing or contradicting the season profile?
4. Are lineups sufficiently available to begin price review?

It still does not claim a calibrated win probability.

## Current limitations

- Bullpen workload remains pending.
- Injury and late-scratch news is not integrated.
- Sportsbook odds remain manual.
- Lineup detection depends on MLB boxscore availability and timing.
- Public MLB API fields can be incomplete or change.
- Journal storage remains session-based.

## Expected remaining roadmap

The first complete product is expected after approximately four additional meaningful releases:

- **v0.5:** Bullpen availability and workload
- **v0.6:** Saved market inputs and target-price logic
- **v0.7:** Live thesis and trigger engine
- **v0.8:** Persistent journal, CLV, and validation analytics

After v0.8, releases should be refinements rather than major missing workflow layers.

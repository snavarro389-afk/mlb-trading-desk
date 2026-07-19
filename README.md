# MLB Trading Desk

## Version: v0.3.1 — Scoring Integrity Pass

This release corrects the interpretation and missing-data problems identified in the v0.3 review.

## What changed

- Missing stats remain `N/A`; no fallback ERA, WHIP, AVG, OBP, SLG, or OPS values are displayed as retrieved data.
- **Research Priority Score** is renamed **Matchup Separation Score**.
- **Preliminary lean** is renamed **Baseball-side advantage**.
- Pregame classifications are now strictly premarket:
  - `TOP MATCHUP`
  - `REVIEW`
  - `LOW SEPARATION`
  - `DATA CHECK`
- Market status remains `MARKET PENDING` until the user explicitly submits two-sided odds.
- Default `-110/-110` inputs no longer count as real market data until submitted.
- The Game Card labels offense as **Season offense baseline**.
- Strategy Packets distinguish:
  - retrieved data
  - inferred app output
  - missing/not-yet-automated data
  - manually entered market data
  - user-entered context
- Dashboard shows the last refresh time.
- Low-confidence games cannot create artificial edges from missing values.

## Important interpretation

The Matchup Separation Score answers:

> How large is the measurable difference between the teams in the current Phase 1 data?

It does not answer:

> What is the exact probability that either team wins?

It also does not establish betting value. Betting value remains unknown until current two-sided sportsbook odds are submitted and reviewed.

## Current automated data

- MLB schedule
- probable starters
- starter season stats
- season offense baselines
- starter and offense component comparisons
- Matchup Separation Score
- data confidence
- market hold and no-vig calculation after explicit odds submission
- structured Strategy Packet
- live MLB game feed

## Current limitations

- Bullpen workload is not integrated.
- Confirmed lineups are not integrated.
- Injuries and late scratches are not integrated.
- Handedness and recent-form splits are not integrated.
- Sportsbook odds remain manual.
- Journal entries remain session-based.
- Live trigger logic is not yet connected to the Game Card.
- The system does not place wagers or guarantee profitable outcomes.

## Installation

```bash
pip install streamlit pandas requests
streamlit run app.py
```

## Next planned phase

After this integrity release is validated in Streamlit, the next build should add:

1. starter handedness and team offense splits
2. confirmed lineup status
3. bullpen usage over the prior three days
4. saved market inputs
5. live thesis triggers

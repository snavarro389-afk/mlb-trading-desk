# Model Methodology

This document is the research record for the MLB Trading Desk. It should contain validated definitions, formulas, assumptions, and limitations developed in the Deep Dive thread.

## Current status

Version 0.1 uses a transparent heuristic live pitcher score. It is not yet a historically calibrated predictive model.

## Current live-score inputs

- Strike percentage
- Pitches per inning
- Walks
- Strikeouts
- Hard-hit percentage allowed
- Average exit velocity allowed
- User-entered market edge

## Current weights

| Component | Weight |
|---|---:|
| Command | 22 |
| Pitch efficiency | 18 |
| Walk control | 12 |
| Strikeouts | 12 |
| Contact suppression | 18 |
| Average exit velocity | 8 |
| Market edge | 10 |

## Definitions

- **Hard hit:** batted ball with exit velocity of at least 95 mph.
- **Barrel proxy:** temporary heuristic, not MLB's official barrel classification.
- **No-vig probability:** each side's raw implied probability divided by the sum of both sides' raw implied probabilities.
- **Fair moneyline:** American odds converted from the user's estimated win probability.

## Research questions

Before treating the score as predictive, test:

1. Which metrics are most useful for F5 outcomes?
2. How quickly do live strike%, velocity, and contact-quality signals stabilize?
3. How should times-through-the-order effects be represented?
4. How should bullpen fatigue be quantified?
5. Does the model improve closing-line value?
6. Which metrics add information beyond the market price?
7. Should F5 and full-game models use separate weights?

## Validation standard

A proposed signal should move into the production model only after:

- The definition is documented.
- The data source is repeatable.
- The signal has a plausible baseball mechanism.
- Historical testing shows useful out-of-sample behavior.
- The result is not explained entirely by market price.
- Limitations and failure modes are recorded.

## Known limitations

The current model excludes or incompletely represents:

- Official barrel classification
- Chase and whiff rates
- Umpire effects
- Weather and park effects
- Official lineup quality
- Complete bullpen availability
- Injuries
- Automatic sportsbook odds
- Historical calibration
- Uncertainty estimates

## Principle

The model should expose its logic. A simpler calibrated model is preferable to a complicated score whose behavior cannot be explained.

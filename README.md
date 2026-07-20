# MLB Trading Desk v0.6 — Market Workspace

v0.6 adds a persistent price-decision workflow to the existing MLB research app.

## What changed

- Two-sided sportsbook market entry
- Automatic implied probability, no-vig probability, and sportsbook hold
- User-defined preferred target price and maximum acceptable price
- Research-alignment check
- Price classifications: `TARGET REACHED`, `ENTER CONSIDERATION`, `WAIT`, `PASS`, or `DATA CHECK`
- Persistent decision evaluations in Supabase
- Decision-history export
- Strategy packet now includes the saved market plan

## Important model boundary

The matchup separation score is **not** treated as a win probability. The no-vig probability is the market's consensus probability after removing sportsbook hold. Until a calibrated probability model is validated, the app does not calculate model edge or EV from the baseball score.

## Upgrade from v0.5.1

1. Run `v0_6_migration.sql` in Supabase SQL Editor.
2. Replace the repository files with this package.
3. Keep existing Streamlit secrets unchanged.
4. Deploy/reboot Streamlit Community Cloud.
5. Confirm `Database: Connected`.
6. Open **Game Card → Market Workspace**, analyze a market, and save a decision evaluation.
7. Confirm the row appears under **Journal → Decision history** and in Supabase table `research_decisions`.

## Price-band rule

A larger American-odds number is always better for the bettor:

- `-135` is better than `-140`
- `+140` is better than `+125`

Therefore, the preferred target must be equal to or greater than the maximum acceptable price. Example:

- Preferred target: `-135`
- Maximum acceptable: `-140`

## Security

Never commit `.streamlit/secrets.toml`. The Supabase service-role/secret credential belongs only in Streamlit Community Cloud Secrets.

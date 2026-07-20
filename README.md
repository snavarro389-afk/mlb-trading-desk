# MLB Trading Desk

## Version: v0.5.1 — Supabase Persistence Foundation

This release replaces session-only storage with durable Supabase tables for games, market snapshots, bets, reviews, and model versions.

## Setup

1. Run `supabase_schema.sql` in Supabase SQL Editor.
2. In Supabase Project Settings → API Keys, copy the Project URL and secret key.
3. Add them to Streamlit Community Cloud → App Settings → Secrets:

```toml
SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_REPLACE_ME"
```

4. Never commit the real key to GitHub.
5. Reboot the app.

The sidebar should display `Database: Connected`.

## Security

Row Level Security is enabled. No public policies are created. The Streamlit server accesses the database with a secret key stored outside GitHub. Supabase secret/service-role keys bypass RLS and must remain private.

## New workflow

- Save a market snapshot from the Game Card.
- Store actual bets in the Persistent Journal.
- Settle bets with result, profit/loss, and closing odds.
- Add postgame thesis and execution reviews.
- Download CSV backups.

## Remaining releases

- v0.6: target prices and market-value workflow
- v0.7: live synchronization and thesis triggers
- v0.8: CLV, calibration, and validation analytics

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st

try:
    from supabase import Client, create_client
except ImportError:
    Client = Any
    create_client = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:
        return None
    return str(value).strip() if value else None


@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Client | None:
    if create_client is None:
        return None
    url = _secret("SUPABASE_URL")
    key = _secret("SUPABASE_SECRET_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def database_status() -> tuple[str, str]:
    if create_client is None:
        return "UNAVAILABLE", "Install the supabase Python package."
    client = get_supabase_client()
    if client is None:
        return "NOT CONFIGURED", "Add SUPABASE_URL and SUPABASE_SECRET_KEY to Streamlit secrets."
    try:
        client.table("model_versions").select("version").limit(1).execute()
        return "CONNECTED", "Supabase connection and required tables are available."
    except Exception as exc:
        return "ERROR", str(exc)


def stable_snapshot_id(game_pk: int | str, market_type: str, selection: str, captured_at: str) -> str:
    raw = f"{game_pk}|{market_type}|{selection}|{captured_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def upsert_game(item: dict[str, Any], game_date: str) -> None:
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase is not configured.")
    payload = {
        "game_pk": int(item["game_pk"]),
        "game_date": game_date,
        "away_team": item["away"],
        "home_team": item["home"],
        "away_starter": item.get("away_starter"),
        "home_starter": item.get("home_starter"),
        "updated_at": utc_now(),
    }
    client.table("games").upsert(payload, on_conflict="game_pk").execute()


def save_market_snapshot(
    item: dict[str, Any],
    game_date: str,
    market_type: str,
    selection: str,
    selection_odds: int,
    opposing_odds: int,
    no_vig_probability: float,
    market_status: str,
    notes: str = "",
) -> str:
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase is not configured.")
    upsert_game(item, game_date)
    captured_at = utc_now()
    snapshot_id = stable_snapshot_id(item["game_pk"], market_type, selection, captured_at)
    payload = {
        "snapshot_id": snapshot_id,
        "game_pk": int(item["game_pk"]),
        "captured_at": captured_at,
        "market_type": market_type,
        "selection": selection,
        "sportsbook": "DraftKings",
        "selection_odds": int(selection_odds),
        "opposing_odds": int(opposing_odds),
        "no_vig_probability": float(no_vig_probability),
        "estimated_probability": None,
        "probability_source": "No calibrated probability model",
        "estimated_edge": None,
        "ev_per_dollar": None,
        "information_quality": item.get("confidence"),
        "premarket_status": item.get("premarket_status"),
        "readiness": item.get("readiness"),
        "bullpen_context": item.get("full_game_context"),
        "decision_label": market_status,
        "model_version": "v0.5.1",
        "notes": notes or None,
        "metadata": {
            "separation_score": item.get("separation_score"),
            "baseball_advantage": item.get("baseball_advantage"),
            "away_bullpen": item.get("away_bullpen", {}).get("status"),
            "home_bullpen": item.get("home_bullpen", {}).get("status"),
        },
    }
    client.table("market_snapshots").insert(payload).execute()
    return snapshot_id


def save_bet(
    snapshot_id: str | None,
    game_pk: int | None,
    game_date: str,
    market_type: str,
    selection: str,
    entry_odds: int,
    stake: float,
    decision_status: str,
    notes: str = "",
) -> str:
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase is not configured.")
    bet_id = str(uuid4())
    payload = {
        "bet_id": bet_id,
        "snapshot_id": snapshot_id,
        "game_pk": int(game_pk) if game_pk else None,
        "game_date": game_date,
        "placed_at": utc_now(),
        "market_type": market_type,
        "selection": selection,
        "entry_odds": int(entry_odds),
        "stake": float(stake),
        "decision_status": decision_status,
        "result": "Open",
        "notes": notes or None,
        "model_version": "v0.5.1",
    }
    client.table("bets").insert(payload).execute()
    return bet_id


def update_bet_result(bet_id: str, result: str, profit_loss: float | None, closing_odds: int | None) -> None:
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase is not configured.")
    payload = {
        "result": result,
        "profit_loss": profit_loss,
        "closing_odds": closing_odds,
        "settled_at": utc_now() if result != "Open" else None,
    }
    client.table("bets").update(payload).eq("bet_id", bet_id).execute()


def save_bet_review(
    bet_id: str,
    thesis: str,
    thesis_killers: str,
    thesis_broken: bool,
    execution_grade: str,
    thesis_grade: str,
    lesson: str,
) -> None:
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase is not configured.")
    payload = {
        "bet_id": bet_id,
        "thesis": thesis or None,
        "thesis_killers": thesis_killers or None,
        "thesis_broken": bool(thesis_broken),
        "execution_grade": execution_grade,
        "thesis_grade": thesis_grade,
        "lesson": lesson or None,
        "reviewed_at": utc_now(),
    }
    client.table("bet_reviews").upsert(payload, on_conflict="bet_id").execute()


def load_table(table: str, order_column: str, limit: int = 1000) -> pd.DataFrame:
    client = get_supabase_client()
    if client is None:
        return pd.DataFrame()
    response = client.table(table).select("*").order(order_column, desc=True).limit(limit).execute()
    return pd.DataFrame(response.data or [])


def load_bets(limit: int = 500) -> pd.DataFrame:
    return load_table("bets", "placed_at", limit)


def load_snapshots(limit: int = 1000) -> pd.DataFrame:
    return load_table("market_snapshots", "captured_at", limit)


def load_reviews(limit: int = 500) -> pd.DataFrame:
    return load_table("bet_reviews", "reviewed_at", limit)


def register_model_version() -> None:
    client = get_supabase_client()
    if client is None:
        return
    payload = {
        "version": "v0.5.1",
        "released_at": utc_now(),
        "weights_json": {
            "starting_pitching": 0.65,
            "matchup_offense": 0.35,
            "offense_season": 0.55,
            "offense_handedness": 0.45,
        },
        "thresholds_json": {
            "top_matchup": 78,
            "review": 64,
            "bullpen_limited_team_pitches": 80,
            "bullpen_concerning_team_pitches": 120,
        },
        "notes": "Supabase persistence foundation.",
    }
    client.table("model_versions").upsert(payload, on_conflict="version").execute()

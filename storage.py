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


CURRENT_MODEL_VERSION = "v0.7"


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
        return (
            "NOT CONFIGURED",
            "Add SUPABASE_URL and SUPABASE_SECRET_KEY to Streamlit secrets.",
        )

    try:
        client.table("model_versions").select("version").limit(1).execute()
        client.table("live_thesis_snapshots").select(
            "live_snapshot_id"
        ).limit(1).execute()

        return (
            "CONNECTED",
            "Supabase connection and required v0.7 tables are available.",
        )

    except Exception as exc:
        return "ERROR", str(exc)


def check_live_thesis_storage() -> dict[str, Any]:
    client = get_supabase_client()

    if client is None:
        return {
            "connected": False,
            "table": "live_thesis_snapshots",
            "error": "Supabase is not configured.",
        }

    try:
        client.table("live_thesis_snapshots").select(
            "live_snapshot_id"
        ).limit(1).execute()

        return {
            "connected": True,
            "table": "live_thesis_snapshots",
            "error": None,
        }

    except Exception as exc:
        return {
            "connected": False,
            "table": "live_thesis_snapshots",
            "error": str(exc),
        }


def stable_snapshot_id(
    game_pk: int | str,
    market_type: str,
    selection: str,
    captured_at: str,
) -> str:
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

    client.table("games").upsert(
        payload,
        on_conflict="game_pk",
    ).execute()


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
    sportsbook: str = "DraftKings",
) -> str:
    client = get_supabase_client()

    if client is None:
        raise RuntimeError("Supabase is not configured.")

    upsert_game(item, game_date)

    captured_at = utc_now()
    snapshot_id = stable_snapshot_id(
        item["game_pk"],
        market_type,
        selection,
        captured_at,
    )

    payload = {
        "snapshot_id": snapshot_id,
        "game_pk": int(item["game_pk"]),
        "captured_at": captured_at,
        "market_type": market_type,
        "selection": selection,
        "sportsbook": sportsbook,
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
        "model_version": "v0.6",
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
        "model_version": "v0.6",
    }

    client.table("bets").insert(payload).execute()

    return bet_id


def update_bet_result(
    bet_id: str,
    result: str,
    profit_loss: float | None,
    closing_odds: int | None,
) -> None:
    client = get_supabase_client()

    if client is None:
        raise RuntimeError("Supabase is not configured.")

    payload = {
        "result": result,
        "profit_loss": profit_loss,
        "closing_odds": closing_odds,
        "settled_at": utc_now() if result != "Open" else None,
    }

    client.table("bets").update(payload).eq(
        "bet_id",
        bet_id,
    ).execute()


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

    client.table("bet_reviews").upsert(
        payload,
        on_conflict="bet_id",
    ).execute()


def load_table(
    table: str,
    order_column: str,
    limit: int = 1000,
) -> pd.DataFrame:
    client = get_supabase_client()

    if client is None:
        return pd.DataFrame()

    response = (
        client.table(table)
        .select("*")
        .order(order_column, desc=True)
        .limit(limit)
        .execute()
    )

    return pd.DataFrame(response.data or [])


def load_bets(limit: int = 500) -> pd.DataFrame:
    return load_table(
        "bets",
        "placed_at",
        limit,
    )


def load_snapshots(limit: int = 1000) -> pd.DataFrame:
    return load_table(
        "market_snapshots",
        "captured_at",
        limit,
    )


def load_reviews(limit: int = 500) -> pd.DataFrame:
    return load_table(
        "bet_reviews",
        "reviewed_at",
        limit,
    )


def register_model_version() -> None:
    client = get_supabase_client()

    if client is None:
        return

    payload = {
        "version": CURRENT_MODEL_VERSION,
        "released_at": utc_now(),
        "weights_json": {
            "starting_pitching": 0.65,
            "matchup_offense": 0.35,
            "offense_season": 0.55,
            "offense_handedness": 0.45,
            "live_starter_command": 0.25,
            "live_contact_quality": 0.25,
            "live_offensive_process": 0.20,
            "live_bullpen_outlook": 0.15,
            "live_game_state": 0.10,
            "live_feed_confidence": 0.05,
        },
        "thresholds_json": {
            "top_matchup": 78,
            "review": 64,
            "bullpen_limited_team_pitches": 80,
            "bullpen_concerning_team_pitches": 120,
            "live_strengthening_score": 35,
            "live_intact_score": 10,
            "live_weakening_score": -10,
            "live_invalidated_score": -35,
            "live_minimum_pitch_count": 15,
        },
        "notes": (
            "v0.7 Live Thesis Engine. Adds persistent live thesis snapshots, "
            "feed integrity status, thesis health scoring, and live price context."
        ),
    }

    client.table("model_versions").upsert(
        payload,
        on_conflict="version",
    ).execute()


def save_research_decision(
    *,
    snapshot_id: str | None,
    item: dict[str, Any],
    game_date: str,
    sportsbook: str,
    market_type: str,
    selection: str,
    current_odds: int,
    opposing_odds: int,
    no_vig_probability: float,
    market_hold: float,
    target_odds: int,
    maximum_odds: int,
    recommendation: str,
    lifecycle_status: str,
    price_status: str,
    final_action: str,
    rationale: str,
    notes: str = "",
) -> str:
    client = get_supabase_client()

    if client is None:
        raise RuntimeError("Supabase is not configured.")

    upsert_game(item, game_date)

    decision_id = str(uuid4())

    payload = {
        "decision_id": decision_id,
        "snapshot_id": snapshot_id,
        "game_pk": int(item["game_pk"]),
        "game_date": game_date,
        "evaluated_at": utc_now(),
        "sportsbook": sportsbook,
        "market_type": market_type,
        "selection": selection,
        "research_lean": item.get("baseball_advantage"),
        "research_score": item.get("separation_score"),
        "confidence": item.get("confidence"),
        "readiness": item.get("readiness"),
        "current_odds": int(current_odds),
        "opposing_odds": int(opposing_odds),
        "no_vig_probability": float(no_vig_probability),
        "market_hold": float(market_hold),
        "target_odds": int(target_odds),
        "maximum_odds": int(maximum_odds),
        "recommendation": recommendation,
        "lifecycle_status": lifecycle_status,
        "price_status": price_status,
        "final_action": final_action,
        "rationale": rationale,
        "notes": notes or None,
        "model_version": "v0.6",
        "metadata": {
            "premarket_status": item.get("premarket_status"),
            "full_game_context": item.get("full_game_context"),
            "lineup_status": item.get("lineup_status"),
        },
    }

    client.table("research_decisions").insert(payload).execute()

    return decision_id


def load_decisions(limit: int = 1000) -> pd.DataFrame:
    return load_table(
        "research_decisions",
        "evaluated_at",
        limit,
    )


def get_latest_research_decision(
    game_pk: int,
) -> dict[str, Any] | None:
    client = get_supabase_client()

    if client is None:
        return None

    response = (
        client.table("research_decisions")
        .select("*")
        .eq("game_pk", int(game_pk))
        .order("evaluated_at", desc=True)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def save_live_thesis_snapshot(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    client = get_supabase_client()

    if client is None:
        raise RuntimeError("Supabase is not configured.")

    required_fields = {
        "game_pk",
        "game_date",
        "thesis_status",
        "decision",
        "feed_status",
    }

    missing_fields = [
        field
        for field in required_fields
        if snapshot.get(field) is None
    ]

    if missing_fields:
        missing_text = ", ".join(sorted(missing_fields))
        raise ValueError(
            f"Live thesis snapshot is missing required fields: {missing_text}"
        )

    payload = dict(snapshot)

    payload["game_pk"] = int(payload["game_pk"])
    payload["game_date"] = str(payload["game_date"])
    payload.setdefault("captured_at", utc_now())
    payload.setdefault("model_version", CURRENT_MODEL_VERSION)
    payload.setdefault("metadata", {})
    payload.setdefault("active_thesis_killers", [])

    integer_fields = (
        "inning",
        "outs",
        "away_score",
        "home_score",
        "current_pitcher_id",
        "pitch_count",
        "strikes",
        "walks",
        "strikeouts",
        "hard_hits",
        "barrels",
        "live_odds",
        "opposing_live_odds",
    )

    for field in integer_fields:
        if payload.get(field) is not None:
            payload[field] = int(payload[field])

    numeric_fields = (
        "strike_rate",
        "first_pitch_strike_rate",
        "thesis_score",
    )

    for field in numeric_fields:
        if payload.get(field) is not None:
            payload[field] = float(payload[field])

    boolean_fields = (
        "runner_on_first",
        "runner_on_second",
        "runner_on_third",
    )

    for field in boolean_fields:
        payload[field] = bool(payload.get(field, False))

    response = (
        client.table("live_thesis_snapshots")
        .insert(payload)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Supabase did not return the saved live thesis snapshot."
        )

    return response.data[0]


def get_live_thesis_snapshots(
    game_pk: int,
    limit: int = 500,
) -> list[dict[str, Any]]:
    client = get_supabase_client()

    if client is None:
        return []

    response = (
        client.table("live_thesis_snapshots")
        .select("*")
        .eq("game_pk", int(game_pk))
        .order("captured_at", desc=True)
        .limit(limit)
        .execute()
    )

    return response.data or []


def get_latest_live_thesis_snapshot(
    game_pk: int,
) -> dict[str, Any] | None:
    client = get_supabase_client()

    if client is None:
        return None

    response = (
        client.table("live_thesis_snapshots")
        .select("*")
        .eq("game_pk", int(game_pk))
        .order("captured_at", desc=True)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def load_live_thesis_snapshots(
    limit: int = 1000,
) -> pd.DataFrame:
    return load_table(
        "live_thesis_snapshots",
        "captured_at",
        limit,
    )

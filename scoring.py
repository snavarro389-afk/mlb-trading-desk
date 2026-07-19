from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from data_sources import get_person_stats, get_team_hitting_stats, safe_number


def team_name(game: dict[str, Any], side: str) -> str:
    return game.get("teams", {}).get(side, {}).get("team", {}).get("name", side.title())


def team_id(game: dict[str, Any], side: str) -> int | None:
    return game.get("teams", {}).get(side, {}).get("team", {}).get("id")


def probable_pitcher(game: dict[str, Any], side: str) -> dict[str, Any]:
    return game.get("teams", {}).get(side, {}).get("probablePitcher", {}) or {}


def optional_float(stats: dict[str, Any], key: str) -> float | None:
    value = stats.get(key)
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pitcher_score(stats: dict[str, Any], prefix: str) -> tuple[float | None, dict[str, float | None]]:
    if not stats:
        return None, {
            f"{prefix}_ERA": None,
            f"{prefix}_WHIP": None,
            f"{prefix}_K9": None,
            f"{prefix}_BB9": None,
            f"{prefix}_HR9": None,
        }

    era = optional_float(stats, "era")
    whip = optional_float(stats, "whip")
    innings = optional_float(stats, "inningsPitched")
    strikeouts = optional_float(stats, "strikeOuts")
    walks = optional_float(stats, "baseOnBalls")
    homers = optional_float(stats, "homeRuns")

    required = [era, whip, innings, strikeouts, walks, homers]
    if any(value is None for value in required) or not innings or innings <= 0:
        return None, {
            f"{prefix}_ERA": era,
            f"{prefix}_WHIP": whip,
            f"{prefix}_K9": None,
            f"{prefix}_BB9": None,
            f"{prefix}_HR9": None,
        }

    k9 = strikeouts * 9 / innings
    bb9 = walks * 9 / innings
    hr9 = homers * 9 / innings
    k_minus_bb9 = (strikeouts - walks) * 9 / innings

    score = (
        50
        + (4.25 - era) * 6
        + (1.35 - whip) * 24
        + (k9 - 8) * 2.2
        + (3 - bb9) * 2
        + (1.2 - hr9) * 3
        + k_minus_bb9 * 1.5
    )
    return round(min(max(score, 0), 100), 1), {
        f"{prefix}_ERA": round(era, 2),
        f"{prefix}_WHIP": round(whip, 2),
        f"{prefix}_K9": round(k9, 2),
        f"{prefix}_BB9": round(bb9, 2),
        f"{prefix}_HR9": round(hr9, 2),
    }


def offense_score(stats: dict[str, Any], prefix: str) -> tuple[float | None, dict[str, float | None]]:
    if not stats:
        return None, {
            f"{prefix}_AVG": None,
            f"{prefix}_OBP": None,
            f"{prefix}_SLG": None,
            f"{prefix}_OPS": None,
            f"{prefix}_K%": None,
            f"{prefix}_BB%": None,
        }

    avg = optional_float(stats, "avg")
    obp = optional_float(stats, "obp")
    slg = optional_float(stats, "slg")
    ops = optional_float(stats, "ops")
    plate_appearances = optional_float(stats, "plateAppearances")
    strikeouts = optional_float(stats, "strikeOuts")
    walks = optional_float(stats, "baseOnBalls")

    required = [avg, obp, slg, plate_appearances, strikeouts, walks]
    if any(value is None for value in required) or not plate_appearances or plate_appearances <= 0:
        return None, {
            f"{prefix}_AVG": avg,
            f"{prefix}_OBP": obp,
            f"{prefix}_SLG": slg,
            f"{prefix}_OPS": ops,
            f"{prefix}_K%": None,
            f"{prefix}_BB%": None,
        }

    if ops is None:
        ops = obp + slg

    k_pct = strikeouts / plate_appearances * 100
    bb_pct = walks / plate_appearances * 100
    score = (
        50
        + (avg - .245) * 120
        + (obp - .315) * 140
        + (slg - .400) * 90
        + (ops - .715) * 75
        + (22.5 - k_pct)
        + (bb_pct - 8) * 1.3
    )
    return round(min(max(score, 0), 100), 1), {
        f"{prefix}_AVG": round(avg, 3),
        f"{prefix}_OBP": round(obp, 3),
        f"{prefix}_SLG": round(slg, 3),
        f"{prefix}_OPS": round(ops, 3),
        f"{prefix}_K%": round(k_pct, 1),
        f"{prefix}_BB%": round(bb_pct, 1),
    }


def premarket_classification(score: float | None, confidence: str) -> str:
    if confidence == "Low" or score is None:
        return "DATA CHECK"
    if score >= 78:
        return "TOP MATCHUP"
    if score >= 64:
        return "REVIEW"
    return "LOW SEPARATION"


def market_classification(
    premarket_status: str,
    confidence: str,
    odds_submitted: bool,
    notes_present: bool = False,
) -> str:
    if not odds_submitted:
        return "MARKET PENDING"
    if confidence == "Low":
        return "DATA CHECK"
    if premarket_status == "TOP MATCHUP":
        return "PRICE SENSITIVE"
    if premarket_status == "REVIEW":
        return "LIVE WATCH"
    if notes_present:
        return "REVIEW CONTEXT"
    return "PASS"


@st.cache_data(ttl=900, show_spinner=False)
def analyze_game(game: dict[str, Any], season: int) -> dict[str, Any]:
    away, home = team_name(game, "away"), team_name(game, "home")
    ap, hp = probable_pitcher(game, "away"), probable_pitcher(game, "home")
    errors: list[str] = []
    datasets: dict[str, dict[str, Any]] = {"aps": {}, "hps": {}, "ahs": {}, "hhs": {}}

    requests = [
        ("aps", ap.get("id"), get_person_stats),
        ("hps", hp.get("id"), get_person_stats),
        ("ahs", team_id(game, "away"), get_team_hitting_stats),
        ("hhs", team_id(game, "home"), get_team_hitting_stats),
    ]

    for key, identifier, fetcher in requests:
        try:
            if identifier:
                datasets[key] = fetcher(int(identifier), season)
        except Exception as exc:
            errors.append(f"{key} unavailable: {exc}")

    asp, aspd = pitcher_score(datasets["aps"], "Away")
    hsp, hspd = pitcher_score(datasets["hps"], "Home")
    aoff, aoffd = offense_score(datasets["ahs"], "Away")
    hoff, hoffd = offense_score(datasets["hhs"], "Home")

    component_availability = {
        "away_starter": asp is not None,
        "home_starter": hsp is not None,
        "away_offense": aoff is not None,
        "home_offense": hoff is not None,
    }
    available_count = sum(component_availability.values())
    completeness = available_count / 4 * 100
    confidence = "High" if completeness == 100 else "Medium" if completeness >= 75 else "Low"

    starter_edge: float | None = None
    offense_edge: float | None = None
    away_net: float | None = None
    home_net: float | None = None
    separation_score: float | None = None
    baseball_advantage = "No reliable advantage"

    if asp is not None and hsp is not None:
        starter_edge = round(hsp - asp, 1)
    if aoff is not None and hoff is not None:
        offense_edge = round(hoff - aoff, 1)

    if None not in (asp, hsp, aoff, hoff):
        away_net = asp * .65 + aoff * .35
        home_net = hsp * .65 + hoff * .35
        gap = abs(away_net - home_net)
        starter_gap = abs(asp - hsp)
        offense_gap = abs(aoff - hoff)
        separation_score = min(100, 48 + starter_gap * .55 + offense_gap * .25 + gap * .45)
        separation_score = round(separation_score, 1)
        baseball_advantage = away if away_net > home_net else home

    premarket_status = premarket_classification(separation_score, confidence)

    return {
        "game_pk": game.get("gamePk"),
        "matchup": f"{away} at {home}",
        "away": away,
        "home": home,
        "away_starter": ap.get("fullName", "TBD"),
        "home_starter": hp.get("fullName", "TBD"),
        "away_sp_score": asp,
        "home_sp_score": hsp,
        "away_off_score": aoff,
        "home_off_score": hoff,
        "starter_edge": starter_edge,
        "offense_edge": offense_edge,
        "baseball_advantage": baseball_advantage,
        "separation_score": separation_score,
        "confidence": confidence,
        "completeness": round(completeness),
        "premarket_status": premarket_status,
        "lineup_status": "Pending integration",
        "bullpen_status": "Phase 2",
        "errors": errors,
        "datasets": datasets,
        "component_availability": component_availability,
        "details": {**aspd, **hspd, **aoffd, **hoffd},
    }


def analyze_slate(games: list[dict[str, Any]], season: int) -> list[dict[str, Any]]:
    progress = st.progress(0, text="Building automated slate analysis...")
    results = []
    for index, game in enumerate(games):
        results.append(analyze_game(game, season))
        progress.progress(
            (index + 1) / max(len(games), 1),
            text=f"Analyzed {index + 1} of {len(games)} games",
        )
    progress.empty()
    return sorted(
        results,
        key=lambda row: (
            row["separation_score"] is not None,
            row["separation_score"] or -1,
        ),
        reverse=True,
    )


def edge_label(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if value is None:
        return "N/A"
    if key == "starter_edge":
        return (
            f"{item['home']} +{value:.1f}"
            if value >= 0
            else f"{item['away']} +{abs(value):.1f}"
        )
    return (
        f"{item['home']} +{value:.1f}"
        if value >= 0
        else f"{item['away']} +{abs(value):.1f}"
    )


def slate_frame(items: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for rank, item in enumerate(items, 1):
        rows.append(
            {
                "Rank": rank,
                "Matchup": item["matchup"],
                "Baseball-side advantage": item["baseball_advantage"],
                "Separation score": item["separation_score"],
                "Starter edge": edge_label(item, "starter_edge"),
                "Season offense edge": edge_label(item, "offense_edge"),
                "Confidence": item["confidence"],
                "Data %": item["completeness"],
                "Premarket status": item["premarket_status"],
                "Market status": "MARKET PENDING",
            }
        )
    return pd.DataFrame(rows)

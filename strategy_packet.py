from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from data_sources import (
    get_lineup_status,
    get_person_pitch_hand,
    get_person_stats,
    get_pitcher_recent,
    get_team_hitting_recent,
    get_team_hitting_split,
    get_team_hitting_stats,
)


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
        }

    era = optional_float(stats, "era")
    whip = optional_float(stats, "whip")
    innings = optional_float(stats, "inningsPitched")
    strikeouts = optional_float(stats, "strikeOuts")
    walks = optional_float(stats, "baseOnBalls")
    homers = optional_float(stats, "homeRuns")

    if any(value is None for value in [era, whip, innings, strikeouts, walks, homers]) or not innings:
        return None, {
            f"{prefix}_ERA": era,
            f"{prefix}_WHIP": whip,
            f"{prefix}_K9": None,
            f"{prefix}_BB9": None,
        }

    k9 = strikeouts * 9 / innings
    bb9 = walks * 9 / innings
    hr9 = homers * 9 / innings
    score = (
        50
        + (4.25 - era) * 6
        + (1.35 - whip) * 24
        + (k9 - 8) * 2.2
        + (3 - bb9) * 2
        + (1.2 - hr9) * 3
        + ((strikeouts - walks) * 9 / innings) * 1.5
    )
    return round(min(max(score, 0), 100), 1), {
        f"{prefix}_ERA": round(era, 2),
        f"{prefix}_WHIP": round(whip, 2),
        f"{prefix}_K9": round(k9, 2),
        f"{prefix}_BB9": round(bb9, 2),
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
    pa = optional_float(stats, "plateAppearances")
    strikeouts = optional_float(stats, "strikeOuts")
    walks = optional_float(stats, "baseOnBalls")

    if any(value is None for value in [avg, obp, slg, pa, strikeouts, walks]) or not pa:
        return None, {
            f"{prefix}_AVG": avg,
            f"{prefix}_OBP": obp,
            f"{prefix}_SLG": slg,
            f"{prefix}_OPS": ops,
            f"{prefix}_K%": None,
            f"{prefix}_BB%": None,
        }

    ops = ops if ops is not None else obp + slg
    k_pct = strikeouts / pa * 100
    bb_pct = walks / pa * 100
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


def recent_trend(recent_score: float | None, season_score: float | None) -> str:
    if recent_score is None or season_score is None:
        return "Unavailable"
    difference = recent_score - season_score
    if difference >= 7:
        return "Heating"
    if difference <= -7:
        return "Cooling"
    return "Stable"


def matchup_offense_score(
    season_score: float | None,
    split_score: float | None,
) -> float | None:
    if season_score is None and split_score is None:
        return None
    if season_score is None:
        return split_score
    if split_score is None:
        return season_score
    return round(season_score * .55 + split_score * .45, 1)


def premarket_classification(score: float | None, confidence: str) -> str:
    if confidence == "Low" or score is None:
        return "DATA CHECK"
    if score >= 78:
        return "TOP MATCHUP"
    if score >= 64:
        return "REVIEW"
    return "LOW SEPARATION"


def readiness_status(lineup_status: str, confidence: str) -> str:
    if confidence == "Low":
        return "DATA CHECK"
    if lineup_status == "Confirmed":
        return "READY FOR PRICE"
    if lineup_status == "Partial":
        return "PARTIAL LINEUPS"
    return "AWAIT LINEUPS"


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
def analyze_game(game: dict[str, Any], season: int, selected_date: str) -> dict[str, Any]:
    away, home = team_name(game, "away"), team_name(game, "home")
    ap, hp = probable_pitcher(game, "away"), probable_pitcher(game, "home")
    away_team_id, home_team_id = team_id(game, "away"), team_id(game, "home")
    errors: list[str] = []

    data: dict[str, Any] = {
        "away_pitcher": {},
        "home_pitcher": {},
        "away_offense": {},
        "home_offense": {},
        "away_split": {},
        "home_split": {},
        "away_recent14": {},
        "home_recent14": {},
        "away_recent30": {},
        "home_recent30": {},
        "away_pitcher_recent30": {},
        "home_pitcher_recent30": {},
    }

    def fetch(key: str, func, *args):
        try:
            if all(arg is not None for arg in args):
                data[key] = func(*args)
        except Exception as exc:
            errors.append(f"{key} unavailable: {exc}")

    fetch("away_pitcher", get_person_stats, ap.get("id"), season)
    fetch("home_pitcher", get_person_stats, hp.get("id"), season)
    fetch("away_offense", get_team_hitting_stats, away_team_id, season)
    fetch("home_offense", get_team_hitting_stats, home_team_id, season)

    away_pitch_hand = None
    home_pitch_hand = None
    try:
        if ap.get("id"):
            away_pitch_hand = get_person_pitch_hand(int(ap["id"]))
    except Exception as exc:
        errors.append(f"away pitcher hand unavailable: {exc}")
    try:
        if hp.get("id"):
            home_pitch_hand = get_person_pitch_hand(int(hp["id"]))
    except Exception as exc:
        errors.append(f"home pitcher hand unavailable: {exc}")

    # Away offense faces the home starter; home offense faces the away starter.
    fetch("away_split", get_team_hitting_split, away_team_id, season, home_pitch_hand)
    fetch("home_split", get_team_hitting_split, home_team_id, season, away_pitch_hand)
    fetch("away_recent14", get_team_hitting_recent, away_team_id, selected_date, 14)
    fetch("home_recent14", get_team_hitting_recent, home_team_id, selected_date, 14)
    fetch("away_recent30", get_team_hitting_recent, away_team_id, selected_date, 30)
    fetch("home_recent30", get_team_hitting_recent, home_team_id, selected_date, 30)
    fetch("away_pitcher_recent30", get_pitcher_recent, ap.get("id"), selected_date, 30)
    fetch("home_pitcher_recent30", get_pitcher_recent, hp.get("id"), selected_date, 30)

    asp, aspd = pitcher_score(data["away_pitcher"], "Away")
    hsp, hspd = pitcher_score(data["home_pitcher"], "Home")
    aoff, aoffd = offense_score(data["away_offense"], "Away")
    hoff, hoffd = offense_score(data["home_offense"], "Home")
    asplit, asplitd = offense_score(data["away_split"], "AwaySplit")
    hsplit, hsplitd = offense_score(data["home_split"], "HomeSplit")
    a14, a14d = offense_score(data["away_recent14"], "Away14")
    h14, h14d = offense_score(data["home_recent14"], "Home14")
    a30, a30d = offense_score(data["away_recent30"], "Away30")
    h30, h30d = offense_score(data["home_recent30"], "Home30")
    apr30, apr30d = pitcher_score(data["away_pitcher_recent30"], "AwayP30")
    hpr30, hpr30d = pitcher_score(data["home_pitcher_recent30"], "HomeP30")

    away_matchup_off = matchup_offense_score(aoff, asplit)
    home_matchup_off = matchup_offense_score(hoff, hsplit)

    game_pk = game.get("gamePk")
    lineup = get_lineup_status(int(game_pk)) if game_pk else {
        "status": "Unavailable",
        "away_count": 0,
        "home_count": 0,
    }

    availability = {
        "away_starter": asp is not None,
        "home_starter": hsp is not None,
        "away_offense": aoff is not None,
        "home_offense": hoff is not None,
        "away_split": asplit is not None,
        "home_split": hsplit is not None,
        "away_hand": away_pitch_hand is not None,
        "home_hand": home_pitch_hand is not None,
    }
    core_count = sum(
        availability[key]
        for key in ["away_starter", "home_starter", "away_offense", "home_offense"]
    )
    matchup_count = sum(
        availability[key]
        for key in ["away_split", "home_split", "away_hand", "home_hand"]
    )
    completeness = (core_count * 15 + matchup_count * 10)  # 100 maximum
    confidence = "High" if completeness >= 90 else "Medium" if completeness >= 65 else "Low"

    starter_edge = round(hsp - asp, 1) if asp is not None and hsp is not None else None
    offense_edge = (
        round(home_matchup_off - away_matchup_off, 1)
        if away_matchup_off is not None and home_matchup_off is not None
        else None
    )

    separation_score = None
    baseball_advantage = "No reliable advantage"
    if None not in (asp, hsp, away_matchup_off, home_matchup_off):
        away_net = asp * .65 + away_matchup_off * .35
        home_net = hsp * .65 + home_matchup_off * .35
        gap = abs(away_net - home_net)
        starter_gap = abs(asp - hsp)
        offense_gap = abs(away_matchup_off - home_matchup_off)
        separation_score = round(
            min(100, 48 + starter_gap * .55 + offense_gap * .25 + gap * .45),
            1,
        )
        baseball_advantage = away if away_net > home_net else home

    premarket_status = premarket_classification(separation_score, confidence)
    readiness = readiness_status(lineup["status"], confidence)

    details = {
        **aspd, **hspd, **aoffd, **hoffd, **asplitd, **hsplitd,
        **a14d, **h14d, **a30d, **h30d, **apr30d, **hpr30d,
    }

    return {
        "game_pk": game_pk,
        "matchup": f"{away} at {home}",
        "away": away,
        "home": home,
        "away_starter": ap.get("fullName", "TBD"),
        "home_starter": hp.get("fullName", "TBD"),
        "away_pitch_hand": away_pitch_hand or "N/A",
        "home_pitch_hand": home_pitch_hand or "N/A",
        "away_sp_score": asp,
        "home_sp_score": hsp,
        "away_pitcher_recent30_score": apr30,
        "home_pitcher_recent30_score": hpr30,
        "away_off_score": aoff,
        "home_off_score": hoff,
        "away_split_score": asplit,
        "home_split_score": hsplit,
        "away_matchup_off_score": away_matchup_off,
        "home_matchup_off_score": home_matchup_off,
        "away_recent14_score": a14,
        "home_recent14_score": h14,
        "away_recent30_score": a30,
        "home_recent30_score": h30,
        "away_recent_trend": recent_trend(a14, aoff),
        "home_recent_trend": recent_trend(h14, hoff),
        "starter_edge": starter_edge,
        "offense_edge": offense_edge,
        "baseball_advantage": baseball_advantage,
        "separation_score": separation_score,
        "confidence": confidence,
        "completeness": round(completeness),
        "premarket_status": premarket_status,
        "readiness": readiness,
        "lineup_status": lineup["status"],
        "away_lineup_count": lineup["away_count"],
        "home_lineup_count": lineup["home_count"],
        "bullpen_status": "Phase 2",
        "errors": errors,
        "component_availability": availability,
        "details": details,
    }


def analyze_slate(games: list[dict[str, Any]], season: int, selected_date: str) -> list[dict[str, Any]]:
    progress = st.progress(0, text="Building matchup intelligence...")
    results = []
    for index, game in enumerate(games):
        results.append(analyze_game(game, season, selected_date))
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
                "Starters": f"{item['away_pitch_hand']} / {item['home_pitch_hand']}",
                "Baseball-side advantage": item["baseball_advantage"],
                "Separation score": item["separation_score"],
                "Starter edge": edge_label(item, "starter_edge"),
                "Matchup offense edge": edge_label(item, "offense_edge"),
                "Recent form": f"{item['away']}: {item['away_recent_trend']} | {item['home']}: {item['home_recent_trend']}",
                "Lineups": item["lineup_status"],
                "Readiness": item["readiness"],
                "Confidence": item["confidence"],
                "Data %": item["completeness"],
                "Premarket status": item["premarket_status"],
            }
        )
    return pd.DataFrame(rows)

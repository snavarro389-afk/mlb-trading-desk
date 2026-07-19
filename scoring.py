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


def pitcher_score(stats: dict[str, Any], prefix: str) -> tuple[float, dict[str, float]]:
    era, whip = safe_number(stats.get("era"), 5.0), safe_number(stats.get("whip"), 1.45)
    ip = max(safe_number(stats.get("inningsPitched")), 1)
    strikeouts, walks, homers = safe_number(stats.get("strikeOuts")), safe_number(stats.get("baseOnBalls")), safe_number(stats.get("homeRuns"))
    k9, bb9, hr9 = strikeouts * 9 / ip, walks * 9 / ip, homers * 9 / ip
    score = 50 + (4.25 - era) * 6 + (1.35 - whip) * 24 + (k9 - 8) * 2.2 + (3 - bb9) * 2 + (1.2 - hr9) * 3 + ((strikeouts - walks) * 9 / ip) * 1.5
    return round(min(max(score, 0), 100), 1), {f"{prefix}_ERA": era, f"{prefix}_WHIP": whip, f"{prefix}_K9": round(k9, 2), f"{prefix}_BB9": round(bb9, 2)}


def offense_score(stats: dict[str, Any], prefix: str) -> tuple[float, dict[str, float]]:
    avg, obp, slg = safe_number(stats.get("avg"), .240), safe_number(stats.get("obp"), .310), safe_number(stats.get("slg"), .390)
    ops = safe_number(stats.get("ops"), obp + slg)
    pa = max(safe_number(stats.get("plateAppearances")), 1)
    k_pct = safe_number(stats.get("strikeOuts")) / pa * 100
    bb_pct = safe_number(stats.get("baseOnBalls")) / pa * 100
    score = 50 + (avg - .245) * 120 + (obp - .315) * 140 + (slg - .400) * 90 + (ops - .715) * 75 + (22.5 - k_pct) + (bb_pct - 8) * 1.3
    return round(min(max(score, 0), 100), 1), {f"{prefix}_AVG": avg, f"{prefix}_OBP": obp, f"{prefix}_SLG": slg, f"{prefix}_OPS": ops, f"{prefix}_K%": round(k_pct, 1), f"{prefix}_BB%": round(bb_pct, 1)}


def classify(score: float, confidence: str) -> str:
    if confidence == "Low": return "DATA CHECK"
    if score >= 78: return "DEEP DIVE"
    if score >= 68: return "PRICE CHECK"
    if score >= 58: return "LIVE WATCH"
    return "PASS"


@st.cache_data(ttl=900, show_spinner=False)
def analyze_game(game: dict[str, Any], season: int) -> dict[str, Any]:
    away, home = team_name(game, "away"), team_name(game, "home")
    ap, hp = probable_pitcher(game, "away"), probable_pitcher(game, "home")
    errors, available = [], 0
    datasets: dict[str, dict[str, Any]] = {"aps": {}, "hps": {}, "ahs": {}, "hhs": {}}
    requests = [("aps", ap.get("id"), get_person_stats), ("hps", hp.get("id"), get_person_stats), ("ahs", team_id(game, "away"), get_team_hitting_stats), ("hhs", team_id(game, "home"), get_team_hitting_stats)]
    for key, identifier, fetcher in requests:
        try:
            if identifier:
                datasets[key] = fetcher(int(identifier), season)
                available += bool(datasets[key])
        except Exception as exc:
            errors.append(f"{key} unavailable: {exc}")
    asp, aspd = pitcher_score(datasets["aps"], "Away")
    hsp, hspd = pitcher_score(datasets["hps"], "Home")
    aoff, aoffd = offense_score(datasets["ahs"], "Away")
    hoff, hoffd = offense_score(datasets["hhs"], "Home")
    anet, hnet = asp * .65 + aoff * .35, hsp * .65 + hoff * .35
    gap, sp_gap, off_gap = abs(anet - hnet), abs(asp - hsp), abs(aoff - hoff)
    score = min(100, 48 + sp_gap * .55 + off_gap * .25 + gap * .45)
    completeness = available / 4 * 100
    confidence = "High" if completeness >= 90 else "Medium" if completeness >= 65 else "Low"
    if confidence == "Low": score = min(score, 67)
    return {"game_pk": game.get("gamePk"), "matchup": f"{away} at {home}", "away": away, "home": home, "away_starter": ap.get("fullName", "TBD"), "home_starter": hp.get("fullName", "TBD"), "away_sp_score": asp, "home_sp_score": hsp, "away_off_score": aoff, "home_off_score": hoff, "starter_edge": round(hsp - asp, 1), "offense_edge": round(hoff - aoff, 1), "lean": away if anet > hnet else home, "research_score": round(score, 1), "confidence": confidence, "completeness": round(completeness), "classification": classify(score, confidence), "lineup_status": "Pending integration", "bullpen_status": "Phase 2", "errors": errors, "datasets": datasets, "details": {**aspd, **hspd, **aoffd, **hoffd}}


def analyze_slate(games: list[dict[str, Any]], season: int) -> list[dict[str, Any]]:
    progress = st.progress(0, text="Building automated slate analysis...")
    results = []
    for index, game in enumerate(games):
        results.append(analyze_game(game, season))
        progress.progress((index + 1) / max(len(games), 1), text=f"Analyzed {index + 1} of {len(games)} games")
    progress.empty()
    return sorted(results, key=lambda row: row["research_score"], reverse=True)


def slate_frame(items: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for rank, item in enumerate(items, 1):
        sp = f"{item['home']} +{item['starter_edge']:.1f}" if item["starter_edge"] >= 0 else f"{item['away']} +{abs(item['starter_edge']):.1f}"
        off = f"{item['home']} +{item['offense_edge']:.1f}" if item["offense_edge"] >= 0 else f"{item['away']} +{abs(item['offense_edge']):.1f}"
        rows.append({"Rank": rank, "Matchup": item["matchup"], "Lean": item["lean"], "Research score": item["research_score"], "Starter edge": sp, "Offense edge": off, "Confidence": item["confidence"], "Data %": item["completeness"], "Next action": item["classification"]})
    return pd.DataFrame(rows)

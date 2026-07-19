from __future__ import annotations

import math
from typing import Any

import pandas as pd
import requests
import streamlit as st

MLB_BASE = "https://statsapi.mlb.com/api"
TIMEOUT = 15


def get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(f"{MLB_BASE}{path}", params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60)
def get_schedule(game_date: str) -> list[dict[str, Any]]:
    payload = get_json("/v1/schedule", {"sportId": 1, "date": game_date, "hydrate": "team,linescore,probablePitcher"})
    return [game for day in payload.get("dates", []) for game in day.get("games", [])]


@st.cache_data(ttl=900)
def get_person_stats(person_id: int, season: int) -> dict[str, Any]:
    payload = get_json(f"/v1/people/{person_id}/stats", {"stats": "season", "group": "pitching", "season": season, "gameType": "R"})
    blocks = payload.get("stats", [])
    splits = blocks[0].get("splits", []) if blocks else []
    return splits[0].get("stat", {}) if splits else {}


@st.cache_data(ttl=900)
def get_team_hitting_stats(team_id: int, season: int) -> dict[str, Any]:
    payload = get_json(f"/v1/teams/{team_id}/stats", {"stats": "season", "group": "hitting", "season": season, "gameType": "R"})
    blocks = payload.get("stats", [])
    splits = blocks[0].get("splits", []) if blocks else []
    return splits[0].get("stat", {}) if splits else {}


@st.cache_data(ttl=10)
def get_live_feed(game_pk: int) -> dict[str, Any]:
    return get_json(f"/v1.1/game/{game_pk}/feed/live")


def safe_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def game_label(game: dict[str, Any]) -> str:
    away = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "Away")
    home = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "Home")
    status = game.get("status", {}).get("detailedState", "")
    return f"{away} at {home} — {status}"


def pitcher_lines(feed: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    box = feed.get("liveData", {}).get("boxscore", {})
    for side in ("away", "home"):
        team = box.get("teams", {}).get(side, {})
        name = team.get("team", {}).get("name", side.title())
        for player in team.get("players", {}).values():
            stats = player.get("stats", {}).get("pitching")
            if not stats:
                continue
            pitches = safe_number(stats.get("numberOfPitches"))
            strikes = safe_number(stats.get("strikes"))
            rows.append({"Team": name, "Pitcher": player.get("person", {}).get("fullName", "Unknown"), "IP": stats.get("inningsPitched", "0.0"), "Pitches": int(pitches), "Strike %": round(strikes / max(pitches, 1) * 100, 1), "K": stats.get("strikeOuts", 0), "BB": stats.get("baseOnBalls", 0), "H": stats.get("hits", 0), "ER": stats.get("earnedRuns", 0), "HR": stats.get("homeRuns", 0)})
    return pd.DataFrame(rows)


def pitch_events(feed: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for play in feed.get("liveData", {}).get("plays", {}).get("allPlays", []):
        matchup = play.get("matchup", {})
        for event in play.get("playEvents", []):
            if not event.get("isPitch"):
                continue
            details, data = event.get("details", {}), event.get("pitchData", {})
            rows.append({"Inning": f"{play.get('about', {}).get('halfInning', '')[:1].upper()}{play.get('about', {}).get('inning')}", "Pitcher": matchup.get("pitcher", {}).get("fullName", "Unknown"), "Batter": matchup.get("batter", {}).get("fullName", "Unknown"), "Pitch Type": details.get("type", {}).get("description", ""), "Call": details.get("description", ""), "Velocity": safe_number(data.get("startSpeed"), math.nan), "Ball": bool(details.get("isBall")), "Strike": bool(details.get("isStrike")), "In Play": bool(details.get("isInPlay"))})
    return pd.DataFrame(rows)


def batted_ball_events(feed: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for play in feed.get("liveData", {}).get("plays", {}).get("allPlays", []):
        matchup = play.get("matchup", {})
        for event in play.get("playEvents", []):
            hit = event.get("hitData")
            if not hit:
                continue
            ev, angle = safe_number(hit.get("launchSpeed"), math.nan), safe_number(hit.get("launchAngle"), math.nan)
            rows.append({"Inning": f"{play.get('about', {}).get('halfInning', '')[:1].upper()}{play.get('about', {}).get('inning')}", "Batter": matchup.get("batter", {}).get("fullName", "Unknown"), "Pitcher": matchup.get("pitcher", {}).get("fullName", "Unknown"), "Result": play.get("result", {}).get("event", ""), "Exit Velo": ev, "Launch Angle": angle, "Hard Hit": bool(not math.isnan(ev) and ev >= 95), "Barrel Proxy": bool(not math.isnan(ev) and not math.isnan(angle) and ev >= 98 and 26 <= angle <= 30)})
    return pd.DataFrame(rows)


def command_summary(pitches: pd.DataFrame) -> pd.DataFrame:
    if pitches.empty:
        return pd.DataFrame()
    frame = pitches.groupby("Pitcher", dropna=False).agg(Pitches=("Pitcher", "size"), Strikes=("Strike", "sum"), Balls=("Ball", "sum"), Avg_Velo=("Velocity", "mean"), Max_Velo=("Velocity", "max")).reset_index()
    frame["Strike %"] = frame["Strikes"] / frame["Pitches"] * 100
    return frame.round({"Avg_Velo": 1, "Max_Velo": 1, "Strike %": 1})


def contact_summary(bbe: pd.DataFrame) -> pd.DataFrame:
    if bbe.empty:
        return pd.DataFrame()
    frame = bbe.groupby("Pitcher", dropna=False).agg(BBE=("Pitcher", "size"), Hard_Hits=("Hard Hit", "sum"), Avg_EV=("Exit Velo", "mean"), Max_EV=("Exit Velo", "max"), Barrel_Proxy=("Barrel Proxy", "sum")).reset_index()
    frame["Hard-Hit %"] = frame["Hard_Hits"] / frame["BBE"] * 100
    return frame.round({"Avg_EV": 1, "Max_EV": 1, "Hard-Hit %": 1})

from __future__ import annotations

import math
from datetime import date, timedelta
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
    payload = get_json(
        "/v1/schedule",
        {
            "sportId": 1,
            "date": game_date,
            "hydrate": "team,linescore,probablePitcher",
        },
    )
    return [game for day in payload.get("dates", []) for game in day.get("games", [])]


@st.cache_data(ttl=900)
def get_person_stats(person_id: int, season: int) -> dict[str, Any]:
    payload = get_json(
        f"/v1/people/{person_id}/stats",
        {"stats": "season", "group": "pitching", "season": season, "gameType": "R"},
    )
    blocks = payload.get("stats", [])
    splits = blocks[0].get("splits", []) if blocks else []
    return splits[0].get("stat", {}) if splits else {}


@st.cache_data(ttl=900)
def get_person_pitch_hand(person_id: int) -> str | None:
    payload = get_json(f"/v1/people/{person_id}")
    people = payload.get("people", [])
    if not people:
        return None
    return people[0].get("pitchHand", {}).get("code")


@st.cache_data(ttl=900)
def get_team_hitting_stats(team_id: int, season: int) -> dict[str, Any]:
    payload = get_json(
        f"/v1/teams/{team_id}/stats",
        {"stats": "season", "group": "hitting", "season": season, "gameType": "R"},
    )
    blocks = payload.get("stats", [])
    splits = blocks[0].get("splits", []) if blocks else []
    return splits[0].get("stat", {}) if splits else {}


@st.cache_data(ttl=900)
def get_team_hitting_split(team_id: int, season: int, pitcher_hand: str) -> dict[str, Any]:
    sit_code = "vl" if pitcher_hand == "L" else "vr"
    payload = get_json(
        f"/v1/teams/{team_id}/stats",
        {
            "stats": "season",
            "group": "hitting",
            "season": season,
            "gameType": "R",
            "sitCodes": sit_code,
        },
    )
    blocks = payload.get("stats", [])
    splits = blocks[0].get("splits", []) if blocks else []
    return splits[0].get("stat", {}) if splits else {}


@st.cache_data(ttl=900)
def get_team_hitting_recent(team_id: int, end_date: str, days: int) -> dict[str, Any]:
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=max(days - 1, 0))
    payload = get_json(
        f"/v1/teams/{team_id}/stats",
        {
            "stats": "byDateRange",
            "group": "hitting",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "gameType": "R",
        },
    )
    blocks = payload.get("stats", [])
    splits = blocks[0].get("splits", []) if blocks else []
    return splits[0].get("stat", {}) if splits else {}


@st.cache_data(ttl=900)
def get_pitcher_recent(person_id: int, end_date: str, days: int = 30) -> dict[str, Any]:
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=max(days - 1, 0))
    payload = get_json(
        f"/v1/people/{person_id}/stats",
        {
            "stats": "byDateRange",
            "group": "pitching",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "gameType": "R",
        },
    )
    blocks = payload.get("stats", [])
    splits = blocks[0].get("splits", []) if blocks else []
    return splits[0].get("stat", {}) if splits else {}


@st.cache_data(ttl=90)
def get_lineup_status(game_pk: int) -> dict[str, Any]:
    try:
        payload = get_json(f"/v1/game/{game_pk}/boxscore")
    except Exception:
        return {"status": "Unavailable", "away_count": 0, "home_count": 0}

    teams = payload.get("teams", {})
    away_order = teams.get("away", {}).get("battingOrder", []) or []
    home_order = teams.get("home", {}).get("battingOrder", []) or []
    away_count = len(away_order)
    home_count = len(home_order)

    if away_count >= 9 and home_count >= 9:
        status = "Confirmed"
    elif away_count or home_count:
        status = "Partial"
    else:
        status = "Awaiting lineups"

    return {"status": status, "away_count": away_count, "home_count": home_count}


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
            rows.append(
                {
                    "Team": name,
                    "Pitcher": player.get("person", {}).get("fullName", "Unknown"),
                    "IP": stats.get("inningsPitched", "0.0"),
                    "Pitches": int(pitches),
                    "Strike %": round(strikes / max(pitches, 1) * 100, 1),
                    "K": stats.get("strikeOuts", 0),
                    "BB": stats.get("baseOnBalls", 0),
                    "H": stats.get("hits", 0),
                    "ER": stats.get("earnedRuns", 0),
                    "HR": stats.get("homeRuns", 0),
                }
            )
    return pd.DataFrame(rows)


def pitch_events(feed: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for play in feed.get("liveData", {}).get("plays", {}).get("allPlays", []):
        matchup = play.get("matchup", {})
        for event in play.get("playEvents", []):
            if not event.get("isPitch"):
                continue
            details, data = event.get("details", {}), event.get("pitchData", {})
            rows.append(
                {
                    "Inning": f"{play.get('about', {}).get('halfInning', '')[:1].upper()}{play.get('about', {}).get('inning')}",
                    "Pitcher": matchup.get("pitcher", {}).get("fullName", "Unknown"),
                    "Batter": matchup.get("batter", {}).get("fullName", "Unknown"),
                    "Pitch Type": details.get("type", {}).get("description", ""),
                    "Call": details.get("description", ""),
                    "Velocity": safe_number(data.get("startSpeed"), math.nan),
                    "Ball": bool(details.get("isBall")),
                    "Strike": bool(details.get("isStrike")),
                    "In Play": bool(details.get("isInPlay")),
                }
            )
    return pd.DataFrame(rows)


def batted_ball_events(feed: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for play in feed.get("liveData", {}).get("plays", {}).get("allPlays", []):
        matchup = play.get("matchup", {})
        for event in play.get("playEvents", []):
            hit = event.get("hitData")
            if not hit:
                continue
            ev = safe_number(hit.get("launchSpeed"), math.nan)
            angle = safe_number(hit.get("launchAngle"), math.nan)
            rows.append(
                {
                    "Inning": f"{play.get('about', {}).get('halfInning', '')[:1].upper()}{play.get('about', {}).get('inning')}",
                    "Batter": matchup.get("batter", {}).get("fullName", "Unknown"),
                    "Pitcher": matchup.get("pitcher", {}).get("fullName", "Unknown"),
                    "Result": play.get("result", {}).get("event", ""),
                    "Exit Velo": ev,
                    "Launch Angle": angle,
                    "Hard Hit": bool(not math.isnan(ev) and ev >= 95),
                    "Barrel Proxy": bool(
                        not math.isnan(ev)
                        and not math.isnan(angle)
                        and ev >= 98
                        and 26 <= angle <= 30
                    ),
                }
            )
    return pd.DataFrame(rows)


def command_summary(pitches: pd.DataFrame) -> pd.DataFrame:
    if pitches.empty:
        return pd.DataFrame()
    frame = (
        pitches.groupby("Pitcher", dropna=False)
        .agg(
            Pitches=("Pitcher", "size"),
            Strikes=("Strike", "sum"),
            Balls=("Ball", "sum"),
            Avg_Velo=("Velocity", "mean"),
            Max_Velo=("Velocity", "max"),
        )
        .reset_index()
    )
    frame["Strike %"] = frame["Strikes"] / frame["Pitches"] * 100
    return frame.round({"Avg_Velo": 1, "Max_Velo": 1, "Strike %": 1})


def contact_summary(bbe: pd.DataFrame) -> pd.DataFrame:
    if bbe.empty:
        return pd.DataFrame()
    frame = (
        bbe.groupby("Pitcher", dropna=False)
        .agg(
            BBE=("Pitcher", "size"),
            Hard_Hits=("Hard Hit", "sum"),
            Avg_EV=("Exit Velo", "mean"),
            Max_EV=("Exit Velo", "max"),
            Barrel_Proxy=("Barrel Proxy", "sum"),
        )
        .reset_index()
    )
    frame["Hard-Hit %"] = frame["Hard_Hits"] / frame["BBE"] * 100
    return frame.round({"Avg_EV": 1, "Max_EV": 1, "Hard-Hit %": 1})


@st.cache_data(ttl=900)
def get_team_recent_games(team_id: int, end_date: str, days: int = 3) -> list[dict[str, Any]]:
    end = date.fromisoformat(end_date) - timedelta(days=1)
    start = end - timedelta(days=max(days - 1, 0))
    payload = get_json(
        "/v1/schedule",
        {
            "sportId": 1,
            "teamId": team_id,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "gameType": "R",
            "hydrate": "team,linescore,probablePitcher",
        },
    )
    games = [game for day in payload.get("dates", []) for game in day.get("games", [])]
    return [
        game
        for game in games
        if game.get("status", {}).get("abstractGameState") == "Final"
    ]


@st.cache_data(ttl=900)
def get_team_bullpen_workload(
    team_id: int,
    end_date: str,
    days: int = 3,
) -> dict[str, Any]:
    games = get_team_recent_games(team_id, end_date, days)
    relievers: dict[int, dict[str, Any]] = {}
    team_pitches = 0
    team_appearances = 0
    games_found = 0

    for game in games:
        game_pk = game.get("gamePk")
        if not game_pk:
            continue
        try:
            feed = get_live_feed(int(game_pk))
        except Exception:
            continue

        box = feed.get("liveData", {}).get("boxscore", {})
        side = None
        for candidate in ("away", "home"):
            candidate_id = (
                box.get("teams", {})
                .get(candidate, {})
                .get("team", {})
                .get("id")
            )
            if candidate_id == team_id:
                side = candidate
                break
        if side is None:
            continue

        games_found += 1
        team_box = box.get("teams", {}).get(side, {})
        probable_id = (
            game.get("teams", {})
            .get(side, {})
            .get("probablePitcher", {})
            .get("id")
        )

        for player in team_box.get("players", {}).values():
            pitching = player.get("stats", {}).get("pitching")
            if not pitching:
                continue

            player_id = player.get("person", {}).get("id")
            if not player_id:
                continue

            games_started = int(safe_number(pitching.get("gamesStarted"), 0))
            is_starter = games_started > 0 or player_id == probable_id
            if is_starter:
                continue

            pitches = int(safe_number(pitching.get("numberOfPitches"), 0))
            if pitches <= 0:
                continue

            record = relievers.setdefault(
                int(player_id),
                {
                    "Pitcher": player.get("person", {}).get("fullName", "Unknown"),
                    "Appearances": 0,
                    "Pitches": 0,
                    "Back-to-back": False,
                    "Dates": [],
                },
            )
            record["Appearances"] += 1
            record["Pitches"] += pitches
            record["Dates"].append(game.get("gameDate", "")[:10])
            team_pitches += pitches
            team_appearances += 1

    for record in relievers.values():
        unique_dates = sorted(set(record["Dates"]))
        record["Dates"] = ", ".join(unique_dates)
        record["Back-to-back"] = len(unique_dates) >= 2

    reliever_rows = sorted(
        relievers.values(),
        key=lambda row: (row["Appearances"], row["Pitches"]),
        reverse=True,
    )

    max_appearances = max((row["Appearances"] for row in reliever_rows), default=0)
    max_pitches = max((row["Pitches"] for row in reliever_rows), default=0)
    multi_day_arms = sum(1 for row in reliever_rows if row["Appearances"] >= 2)

    if max_appearances >= 3 or max_pitches >= 45 or team_pitches >= 120:
        status = "CONCERNING"
        availability_score = 35
    elif max_appearances >= 2 or max_pitches >= 30 or team_pitches >= 80:
        status = "LIMITED"
        availability_score = 60
    elif games_found == 0:
        status = "NO RECENT GAME DATA"
        availability_score = None
    else:
        status = "RESTED"
        availability_score = 85

    return {
        "status": status,
        "availability_score": availability_score,
        "games_found": games_found,
        "team_pitches": team_pitches,
        "team_appearances": team_appearances,
        "multi_day_arms": multi_day_arms,
        "max_reliever_pitches": max_pitches,
        "relievers": reliever_rows,
    }

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
                    "Pitcher ID": matchup.get("pitcher", {}).get("id"),
                    "Batter": matchup.get("batter", {}).get("fullName", "Unknown"),
                    "Batter ID": matchup.get("batter", {}).get("id"),
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
                    "Batter ID": matchup.get("batter", {}).get("id"),
                    "Pitcher": matchup.get("pitcher", {}).get("fullName", "Unknown"),
                    "Pitcher ID": matchup.get("pitcher", {}).get("id"),
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



def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _team_side_from_name(
    feed: dict[str, Any],
    team_name: str,
) -> str | None:
    teams = feed.get("gameData", {}).get("teams", {})
    normalized = str(team_name or "").strip().lower()

    for side in ("away", "home"):
        candidate = str(
            teams.get(side, {}).get("name", "")
        ).strip().lower()
        if candidate == normalized:
            return side

    return None


def _team_pitcher_ids(
    feed: dict[str, Any],
    side: str,
) -> list[int]:
    team_box = (
        feed.get("liveData", {})
        .get("boxscore", {})
        .get("teams", {})
        .get(side, {})
    )
    return [
        safe_int(player_id)
        for player_id in team_box.get("pitchers", [])
        if safe_int(player_id) > 0
    ]


def _team_batter_ids(
    feed: dict[str, Any],
    side: str,
) -> set[int]:
    team_box = (
        feed.get("liveData", {})
        .get("boxscore", {})
        .get("teams", {})
        .get(side, {})
    )
    return {
        safe_int(player_id)
        for player_id in team_box.get("batters", [])
        if safe_int(player_id) > 0
    }


def _player_record(
    feed: dict[str, Any],
    side: str,
    player_id: int,
) -> dict[str, Any]:
    players = (
        feed.get("liveData", {})
        .get("boxscore", {})
        .get("teams", {})
        .get(side, {})
        .get("players", {})
    )
    return (
        players.get(f"ID{player_id}")
        or players.get(str(player_id))
        or {}
    )


def _starter_id(
    feed: dict[str, Any],
    side: str,
) -> int | None:
    for pitcher_id in _team_pitcher_ids(feed, side):
        record = _player_record(feed, side, pitcher_id)
        stats = record.get("stats", {}).get("pitching", {})
        if safe_int(stats.get("gamesStarted")) > 0:
            return pitcher_id

    probable_id = safe_int(
        feed.get("gameData", {})
        .get("probablePitchers", {})
        .get(side, {})
        .get("id")
    )
    return probable_id if probable_id > 0 else None


def _current_pitcher(
    feed: dict[str, Any],
) -> dict[str, Any]:
    pitcher = (
        feed.get("liveData", {})
        .get("plays", {})
        .get("currentPlay", {})
        .get("matchup", {})
        .get("pitcher", {})
    )
    return {
        "id": safe_int(pitcher.get("id")) or None,
        "name": pitcher.get("fullName"),
    }


def _runner_state(
    feed: dict[str, Any],
) -> dict[str, bool]:
    offense = (
        feed.get("liveData", {})
        .get("linescore", {})
        .get("offense", {})
    )
    return {
        "runner_on_first": bool(offense.get("first")),
        "runner_on_second": bool(offense.get("second")),
        "runner_on_third": bool(offense.get("third")),
    }


def _first_pitch_strike_rate(
    feed: dict[str, Any],
    pitcher_id: int | None,
) -> float | None:
    if not pitcher_id:
        return None

    first_pitches = 0
    first_pitch_strikes = 0

    for play in (
        feed.get("liveData", {})
        .get("plays", {})
        .get("allPlays", [])
    ):
        if safe_int(
            play.get("matchup", {})
            .get("pitcher", {})
            .get("id")
        ) != pitcher_id:
            continue

        first_pitch = next(
            (
                event
                for event in play.get("playEvents", [])
                if event.get("isPitch")
            ),
            None,
        )
        if not first_pitch:
            continue

        first_pitches += 1
        if bool(first_pitch.get("details", {}).get("isStrike")):
            first_pitch_strikes += 1

    if first_pitches == 0:
        return None

    return first_pitch_strikes / first_pitches


def _team_offense_totals(
    feed: dict[str, Any],
    side: str,
    pitches: pd.DataFrame,
    bbe: pd.DataFrame,
) -> dict[str, int]:
    team_box = (
        feed.get("liveData", {})
        .get("boxscore", {})
        .get("teams", {})
        .get(side, {})
    )
    batting = team_box.get("teamStats", {}).get("batting", {})
    batter_ids = _team_batter_ids(feed, side)

    pitches_seen = (
        int(pitches["Batter ID"].isin(batter_ids).sum())
        if not pitches.empty
        and "Batter ID" in pitches.columns
        and batter_ids
        else 0
    )

    if (
        not bbe.empty
        and "Batter ID" in bbe.columns
        and batter_ids
    ):
        team_bbe = bbe[bbe["Batter ID"].isin(batter_ids)]
        hard_hits = int(team_bbe["Hard Hit"].sum())
        barrels = int(team_bbe["Barrel Proxy"].sum())
    else:
        hard_hits = 0
        barrels = 0

    plate_appearances = safe_int(
        batting.get("plateAppearances")
    )
    if plate_appearances <= 0:
        plate_appearances = (
            safe_int(batting.get("atBats"))
            + safe_int(batting.get("baseOnBalls"))
            + safe_int(batting.get("hitByPitch"))
            + safe_int(batting.get("sacFlies"))
            + safe_int(batting.get("sacBunts"))
        )

    return {
        "plate_appearances": plate_appearances,
        "hard_hits": hard_hits,
        "barrels": barrels,
        "walks": safe_int(batting.get("baseOnBalls")),
        "strikeouts": safe_int(batting.get("strikeOuts")),
        "pitches_seen": pitches_seen,
    }


def extract_live_thesis_inputs(
    feed: dict[str, Any],
    selected_team: str,
) -> dict[str, Any]:
    """
    Map an MLB live feed to the v0.7 Live Thesis Engine inputs.

    Hard-hit and barrel values use the same proxies as
    batted_ball_events(): 95+ mph for hard hit and the existing
    98+ mph / 26-30 degree barrel proxy.
    """
    selected_side = _team_side_from_name(feed, selected_team)
    if selected_side is None:
        raise ValueError(
            "Selected team does not match the away or home team in the MLB feed."
        )

    opponent_side = "home" if selected_side == "away" else "away"
    game_data = feed.get("gameData", {})
    linescore = feed.get("liveData", {}).get("linescore", {})
    teams = game_data.get("teams", {})

    away_team = teams.get("away", {}).get("name", "Away")
    home_team = teams.get("home", {}).get("name", "Home")
    opponent_team = teams.get(opponent_side, {}).get(
        "name",
        "Opponent",
    )

    away_score = safe_int(
        linescore.get("teams", {})
        .get("away", {})
        .get("runs")
    )
    home_score = safe_int(
        linescore.get("teams", {})
        .get("home", {})
        .get("runs")
    )

    all_pitches = pitch_events(feed)
    all_bbe = batted_ball_events(feed)

    starter_id = _starter_id(feed, selected_side)
    current_pitcher = _current_pitcher(feed)
    tracked_pitcher_id = starter_id or current_pitcher["id"]

    tracked_record = (
        _player_record(feed, selected_side, tracked_pitcher_id)
        if tracked_pitcher_id
        else {}
    )
    tracked_stats = tracked_record.get("stats", {}).get(
        "pitching",
        {},
    )
    tracked_name = (
        tracked_record.get("person", {}).get("fullName")
        or current_pitcher["name"]
    )

    if (
        not all_bbe.empty
        and tracked_pitcher_id
        and "Pitcher ID" in all_bbe.columns
    ):
        pitcher_bbe = all_bbe[
            all_bbe["Pitcher ID"] == tracked_pitcher_id
        ]
    else:
        pitcher_bbe = pd.DataFrame()

    pitch_count = safe_int(
        tracked_stats.get("numberOfPitches")
    )
    strikes = safe_int(tracked_stats.get("strikes"))

    if (
        pitch_count <= 0
        and not all_pitches.empty
        and tracked_pitcher_id
        and "Pitcher ID" in all_pitches.columns
    ):
        pitcher_pitches = all_pitches[
            all_pitches["Pitcher ID"] == tracked_pitcher_id
        ]
        pitch_count = len(pitcher_pitches)
        strikes = int(pitcher_pitches["Strike"].sum())

    offense = _team_offense_totals(
        feed,
        selected_side,
        all_pitches,
        all_bbe,
    )
    runners = _runner_state(feed)

    selected_score = (
        away_score if selected_side == "away" else home_score
    )
    opponent_score = (
        home_score if selected_side == "away" else away_score
    )

    return {
        "away_team": away_team,
        "home_team": home_team,
        "selected_team": selected_team,
        "opponent_team": opponent_team,
        "selected_side": selected_side,
        "favored_team_is_home": selected_side == "home",
        "away_score": away_score,
        "home_score": home_score,
        "favored_score": selected_score,
        "opponent_score": opponent_score,
        "inning": safe_int(linescore.get("currentInning")),
        "inning_half": linescore.get("inningState") or "",
        "outs": safe_int(linescore.get("outs")),
        **runners,
        "game_status": game_data.get("status", {}).get(
            "detailedState",
            "",
        ),
        "current_pitcher_id": current_pitcher["id"],
        "current_pitcher_name": current_pitcher["name"],
        "tracked_pitcher_id": tracked_pitcher_id,
        "tracked_pitcher_name": tracked_name,
        "starter_id": starter_id,
        "favored_starter_still_active": bool(
            starter_id
            and current_pitcher["id"] == starter_id
        ),
        "pitch_count": pitch_count,
        "strikes": strikes,
        "strike_rate": (
            strikes / pitch_count if pitch_count > 0 else None
        ),
        "first_pitch_strike_rate": _first_pitch_strike_rate(
            feed,
            tracked_pitcher_id,
        ),
        "pitcher_walks": safe_int(
            tracked_stats.get("baseOnBalls")
        ),
        "pitcher_strikeouts": safe_int(
            tracked_stats.get("strikeOuts")
        ),
        "batters_faced": safe_int(
            tracked_stats.get("battersFaced")
        ),
        "pitcher_hard_hits_allowed": (
            int(pitcher_bbe["Hard Hit"].sum())
            if not pitcher_bbe.empty
            else 0
        ),
        "pitcher_barrels_allowed": (
            int(pitcher_bbe["Barrel Proxy"].sum())
            if not pitcher_bbe.empty
            else 0
        ),
        "balls_in_play_against_pitcher": len(pitcher_bbe),
        "favored_plate_appearances": offense[
            "plate_appearances"
        ],
        "favored_hard_hits": offense["hard_hits"],
        "favored_barrels": offense["barrels"],
        "favored_walks": offense["walks"],
        "favored_strikeouts": offense["strikeouts"],
        "favored_pitches_seen": offense["pitches_seen"],
    }


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
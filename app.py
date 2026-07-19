from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
import requests
import streamlit as st

MLB_BASE = "https://statsapi.mlb.com/api"
TIMEOUT = 15

st.set_page_config(page_title="MLB Trading Desk", page_icon="⚾", layout="wide")


@dataclass
class MarketPrice:
    american_odds: int

    @property
    def implied_probability(self) -> float:
        if self.american_odds < 0:
            return abs(self.american_odds) / (abs(self.american_odds) + 100)
        return 100 / (self.american_odds + 100)


def american_from_probability(probability: float) -> int:
    probability = min(max(probability, 0.001), 0.999)
    if probability >= 0.5:
        return round(-100 * probability / (1 - probability))
    return round(100 * (1 - probability) / probability)


def get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(f"{MLB_BASE}{path}", params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=30)
def get_schedule(game_date: str) -> list[dict[str, Any]]:
    payload = get_json(
        "/v1/schedule",
        {
            "sportId": 1,
            "date": game_date,
            "hydrate": "team,linescore,probablePitcher",
        },
    )
    games: list[dict[str, Any]] = []
    for day in payload.get("dates", []):
        games.extend(day.get("games", []))
    return games


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


def probable_pitcher_name(game: dict[str, Any], side: str) -> str:
    return (
        game.get("teams", {})
        .get(side, {})
        .get("probablePitcher", {})
        .get("fullName", "TBD")
    )


def pitcher_lines(feed: dict[str, Any]) -> pd.DataFrame:
    box = feed.get("liveData", {}).get("boxscore", {})
    rows: list[dict[str, Any]] = []

    for side in ("away", "home"):
        team = box.get("teams", {}).get(side, {})
        team_name = team.get("team", {}).get("name", side.title())
        players = team.get("players", {})

        for player in players.values():
            stats = player.get("stats", {}).get("pitching")
            if not stats:
                continue
            rows.append(
                {
                    "Team": team_name,
                    "Pitcher": player.get("person", {}).get("fullName", "Unknown"),
                    "IP": stats.get("inningsPitched", "0.0"),
                    "Pitches": stats.get("numberOfPitches", 0),
                    "Strikes": stats.get("strikes", 0),
                    "Strike %": (
                        safe_number(stats.get("strikes"))
                        / max(safe_number(stats.get("numberOfPitches")), 1)
                    ),
                    "K": stats.get("strikeOuts", 0),
                    "BB": stats.get("baseOnBalls", 0),
                    "H": stats.get("hits", 0),
                    "ER": stats.get("earnedRuns", 0),
                    "HR": stats.get("homeRuns", 0),
                    "Batters Faced": stats.get("battersFaced", 0),
                }
            )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["Strike %"] = (frame["Strike %"] * 100).round(1)
    return frame


def batted_ball_events(feed: dict[str, Any]) -> pd.DataFrame:
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
    rows: list[dict[str, Any]] = []

    for play in plays:
        matchup = play.get("matchup", {})
        batter = matchup.get("batter", {}).get("fullName", "Unknown")
        pitcher = matchup.get("pitcher", {}).get("fullName", "Unknown")
        result = play.get("result", {}).get("event", "")
        inning = play.get("about", {}).get("inning")
        half = play.get("about", {}).get("halfInning", "")

        for event in play.get("playEvents", []):
            hit = event.get("hitData")
            if not hit:
                continue
            launch_speed = safe_number(hit.get("launchSpeed"), math.nan)
            launch_angle = safe_number(hit.get("launchAngle"), math.nan)
            total_distance = safe_number(hit.get("totalDistance"), math.nan)
            rows.append(
                {
                    "Inning": f"{half[:1].upper()}{inning}",
                    "Batter": batter,
                    "Pitcher": pitcher,
                    "Result": result,
                    "Exit Velo": launch_speed,
                    "Launch Angle": launch_angle,
                    "Distance": total_distance,
                    "Hard Hit": bool(not math.isnan(launch_speed) and launch_speed >= 95),
                    "Barrel Proxy": bool(
                        not math.isnan(launch_speed)
                        and not math.isnan(launch_angle)
                        and launch_speed >= 98
                        and 26 <= launch_angle <= 30
                    ),
                }
            )
    return pd.DataFrame(rows)


def pitch_events(feed: dict[str, Any]) -> pd.DataFrame:
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
    rows: list[dict[str, Any]] = []

    for play in plays:
        matchup = play.get("matchup", {})
        pitcher = matchup.get("pitcher", {}).get("fullName", "Unknown")
        batter = matchup.get("batter", {}).get("fullName", "Unknown")
        inning = play.get("about", {}).get("inning")
        half = play.get("about", {}).get("halfInning", "")

        for event in play.get("playEvents", []):
            if not event.get("isPitch"):
                continue
            details = event.get("details", {})
            pitch_data = event.get("pitchData", {})
            rows.append(
                {
                    "Inning": f"{half[:1].upper()}{inning}",
                    "Pitcher": pitcher,
                    "Batter": batter,
                    "Pitch Type": details.get("type", {}).get("description", ""),
                    "Call": details.get("description", ""),
                    "Velocity": safe_number(pitch_data.get("startSpeed"), math.nan),
                    "Zone": pitch_data.get("zone"),
                    "Ball": bool(details.get("isBall")),
                    "Strike": bool(details.get("isStrike")),
                    "In Play": bool(details.get("isInPlay")),
                }
            )
    return pd.DataFrame(rows)


def contact_summary(bbe: pd.DataFrame) -> pd.DataFrame:
    if bbe.empty:
        return pd.DataFrame()
    grouped = (
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
    grouped["Hard-Hit %"] = grouped["Hard_Hits"] / grouped["BBE"] * 100
    return grouped.round({"Avg_EV": 1, "Max_EV": 1, "Hard-Hit %": 1})


def command_summary(pitches: pd.DataFrame) -> pd.DataFrame:
    if pitches.empty:
        return pd.DataFrame()
    grouped = (
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
    grouped["Strike %"] = grouped["Strikes"] / grouped["Pitches"] * 100
    return grouped.round({"Avg_Velo": 1, "Max_Velo": 1, "Strike %": 1})


def calculate_live_score(
    strike_pct: float,
    pitches_per_inning: float,
    walks: int,
    strikeouts: int,
    hard_hit_pct: float,
    avg_ev: float,
    market_edge_pct: float,
) -> float:
    command = min(max((strike_pct - 55) / 15, 0), 1) * 22
    efficiency = min(max((22 - pitches_per_inning) / 9, 0), 1) * 18
    control = max(0, 12 - walks * 4)
    swing_miss = min(strikeouts / 6, 1) * 12
    contact = min(max((50 - hard_hit_pct) / 35, 0), 1) * 18
    ev_score = min(max((93 - avg_ev) / 12, 0), 1) * 8
    market = min(max(market_edge_pct / 5, 0), 1) * 10
    return round(command + efficiency + control + swing_miss + contact + ev_score + market, 1)


def render_home(games: list[dict[str, Any]], selected_date: str) -> None:
    st.header("Today's Slate")
    st.caption(
        "Use this workspace on every MLB game day, including weekends. "
        "Postseason-specific logic will be added later."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Games scheduled", len(games))
    c2.metric("Date", selected_date)
    c3.metric("Workflow", "Research → Classify → Track")

    if not games:
        st.info("No MLB games found for the selected date.")
        return

    rows = []
    for game in games:
        away = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "Away")
        home = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "Home")
        rows.append(
            {
                "Matchup": f"{away} at {home}",
                "Away starter": probable_pitcher_name(game, "away"),
                "Home starter": probable_pitcher_name(game, "home"),
                "Status": game.get("status", {}).get("detailedState", ""),
                "Desk status": "UNREVIEWED",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Desk workflow")
    st.markdown(
        """
1. Open **Pregame** and classify selected games as BET, WATCH, or PASS.
2. Use **Live** for pitch-level confirmation and updated pricing.
3. Record every wager and meaningful pass in **Journal**.
"""
    )


def render_pregame(games: list[dict[str, Any]]) -> None:
    st.header("Pregame Review")
    if not games:
        st.info("No games available for this date.")
        return

    labels = {game_label(game): game for game in games}
    choice = st.selectbox("Select game for pregame review", list(labels), key="pregame_game")
    game = labels[choice]

    away = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "Away")
    home = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "Home")

    st.subheader(f"{away} at {home}")
    p1, p2 = st.columns(2)
    p1.metric("Away probable starter", probable_pitcher_name(game, "away"))
    p2.metric("Home probable starter", probable_pitcher_name(game, "home"))

    st.markdown("### Research checklist")
    categories = {
        "Starting pitching": [
            "FIP / xFIP / WHIP / K-BB%",
            "Recent form and pitch-count trend",
            "Velocity, pitch mix, hard-hit%, barrel%",
        ],
        "Offense": [
            "Recent splits vs starter handedness",
            "wRC+ / OPS / ISO / K% / BB%",
            "Official lineup and injuries",
        ],
        "Bullpen": [
            "Prior three days of usage",
            "High-leverage reliever availability",
        ],
        "Market": [
            "Opening vs current price",
            "No-vig probability and fair line",
            "F5 vs full-game value",
        ],
    }

    for category, items in categories.items():
        with st.expander(category, expanded=True):
            for item in items:
                st.checkbox(item, key=f"{choice}-{category}-{item}")

    st.markdown("### Desk classification")
    col1, col2 = st.columns(2)
    with col1:
        classification = st.selectbox(
            "Current classification",
            ["UNREVIEWED", "BET", "WATCH", "PASS"],
            key=f"classification-{choice}",
        )
        market = st.selectbox(
            "Preferred market",
            ["None", "Full-game ML", "F5 ML", "F5 -0.5", "Run line", "Total", "Live only"],
            key=f"market-{choice}",
        )
    with col2:
        fair_line = st.number_input(
            "Estimated fair American odds",
            value=-110,
            step=1,
            key=f"fair-{choice}",
        )
        minimum_price = st.number_input(
            "Minimum acceptable price",
            value=-110,
            step=1,
            key=f"minimum-{choice}",
        )

    notes = st.text_area(
        "Thesis and live triggers",
        placeholder="Example: WATCH LIVE. Enter only if starter velocity is normal, command is stable, and price improves.",
        key=f"notes-{choice}",
    )

    st.info(
        f"Current desk view: **{classification}** | Market: **{market}** | "
        f"Fair: **{fair_line:+d}** | Minimum acceptable: **{minimum_price:+d}**"
    )
    if notes:
        st.write(notes)


def render_live(games: list[dict[str, Any]]) -> None:
    st.header("Live Game Desk")
    st.caption(
        "Live MLB data, contact quality, command, and manual sportsbook pricing. "
        "The score is a decision aid—not a guarantee or automated betting recommendation."
    )

    if not games:
        st.info("No MLB games found for the selected date.")
        return

    labels = {game_label(game): game.get("gamePk") for game in games}
    choice = st.selectbox("Select live game", list(labels), key="live_game")
    game_pk = labels[choice]

    try:
        feed = get_live_feed(int(game_pk))
    except Exception as exc:
        st.error(f"Could not retrieve live game feed: {exc}")
        return

    game_data = feed.get("gameData", {})
    live_data = feed.get("liveData", {})
    linescore = live_data.get("linescore", {})
    status = game_data.get("status", {}).get("detailedState", "")

    away_name = game_data.get("teams", {}).get("away", {}).get("name", "Away")
    home_name = game_data.get("teams", {}).get("home", {}).get("name", "Home")
    away_runs = linescore.get("teams", {}).get("away", {}).get("runs", 0)
    home_runs = linescore.get("teams", {}).get("home", {}).get("runs", 0)
    inning_state = linescore.get("inningState", "")
    inning = linescore.get("currentInning", "")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(away_name, away_runs)
    c2.metric(home_name, home_runs)
    c3.metric("Game state", f"{inning_state} {inning}".strip())
    c4.metric("Status", status)

    pitchers = pitcher_lines(feed)
    pitches = pitch_events(feed)
    bbe = batted_ball_events(feed)
    command = command_summary(pitches)
    contact = contact_summary(bbe)

    st.subheader("Pitching line")
    st.dataframe(pitchers, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Command and velocity")
        st.dataframe(command, use_container_width=True, hide_index=True)
    with right:
        st.subheader("Contact allowed")
        st.dataframe(contact, use_container_width=True, hide_index=True)

    st.subheader("Live market input")
    market_col1, market_col2, market_col3 = st.columns(3)
    with market_col1:
        away_odds = st.number_input(f"{away_name} live ML", value=-110, step=1)
    with market_col2:
        home_odds = st.number_input(f"{home_name} live ML", value=-110, step=1)
    with market_col3:
        model_away_prob = st.slider(
            f"Your estimated {away_name} win probability",
            min_value=0.01,
            max_value=0.99,
            value=0.50,
            step=0.005,
        )

    away_raw = MarketPrice(int(away_odds)).implied_probability
    home_raw = MarketPrice(int(home_odds)).implied_probability
    market_sum = away_raw + home_raw
    away_no_vig = away_raw / market_sum
    home_no_vig = home_raw / market_sum
    edge = model_away_prob - away_no_vig

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"{away_name} no-vig", f"{away_no_vig:.1%}")
    m2.metric(f"{home_name} no-vig", f"{home_no_vig:.1%}")
    m3.metric("Model edge", f"{edge:+.1%}")
    m4.metric("Model fair ML", american_from_probability(model_away_prob))

    st.subheader("Pitcher live score")
    score_rows = []
    if not pitchers.empty:
        for _, row in pitchers.iterrows():
            pitcher_name = row["Pitcher"]
            ip_text = str(row["IP"])
            try:
                full, partial = ip_text.split(".")
                innings_float = float(full) + int(partial) / 3
            except Exception:
                innings_float = max(safe_number(ip_text), 0.1)
            innings_float = max(innings_float, 0.1)

            c_row = contact[contact["Pitcher"] == pitcher_name] if not contact.empty else pd.DataFrame()
            hh_pct = safe_number(c_row.iloc[0]["Hard-Hit %"], 0) if not c_row.empty else 0
            avg_ev = safe_number(c_row.iloc[0]["Avg_EV"], 85) if not c_row.empty else 85

            score_rows.append(
                {
                    "Pitcher": pitcher_name,
                    "Live Score": calculate_live_score(
                        strike_pct=safe_number(row["Strike %"]),
                        pitches_per_inning=safe_number(row["Pitches"]) / innings_float,
                        walks=int(safe_number(row["BB"])),
                        strikeouts=int(safe_number(row["K"])),
                        hard_hit_pct=hh_pct,
                        avg_ev=avg_ev,
                        market_edge_pct=max(edge * 100, 0),
                    ),
                    "Pitches/IP": round(safe_number(row["Pitches"]) / innings_float, 1),
                    "Strike %": row["Strike %"],
                    "K-BB": int(safe_number(row["K"]) - safe_number(row["BB"])),
                    "Hard-Hit %": hh_pct,
                    "Avg EV": avg_ev,
                }
            )

    score_df = pd.DataFrame(score_rows)
    if not score_df.empty:
        st.dataframe(
            score_df.sort_values("Live Score", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("Batted-ball event log"):
        st.dataframe(bbe, use_container_width=True, hide_index=True)

    with st.expander("Pitch-by-pitch event log"):
        st.dataframe(pitches, use_container_width=True, hide_index=True)

    with st.expander("Interpretation bands"):
        st.markdown(
            """
- **80–100:** Strong live process; enter only when market price still offers a meaningful edge.
- **70–79:** Watch closely; one more confirming inning may be appropriate.
- **60–69:** Mixed process; usually pass.
- **Below 60:** Thesis weak or insufficient evidence.
"""
        )


def render_journal() -> None:
    st.header("Bet Journal")
    st.caption(
        "Entries remain available during the current browser session. "
        "Download the CSV before closing the session."
    )

    if "journal_entries" not in st.session_state:
        st.session_state.journal_entries = []

    c1, c2, c3 = st.columns(3)
    with c1:
        entry_date = st.date_input("Date", value=date.today(), key="journal_date")
        game = st.text_input("Game", placeholder="Mets at Phillies")
        market = st.selectbox(
            "Market",
            ["Full-game ML", "F5 ML", "F5 -0.5", "Run line", "Total", "Player prop", "No bet / tracked pass"],
        )
    with c2:
        selection = st.text_input("Selection", placeholder="Phillies F5 -0.5")
        odds = st.number_input("Entry odds", value=-110, step=1)
        stake = st.number_input("Stake", min_value=0.0, value=5.0, step=1.0)
    with c3:
        classification = st.selectbox("Pregame classification", ["BET", "WATCH", "PASS"])
        result = st.selectbox("Result", ["Open", "Win", "Loss", "Push", "No bet"])
        closing_odds = st.number_input("Closing odds", value=-110, step=1)

    thesis = st.text_area("Reason, live trigger, and postgame lesson")

    if st.button("Add journal entry", type="primary"):
        st.session_state.journal_entries.append(
            {
                "Date": entry_date.isoformat(),
                "Game": game,
                "Market": market,
                "Selection": selection,
                "Entry Odds": int(odds),
                "Stake": float(stake),
                "Classification": classification,
                "Result": result,
                "Closing Odds": int(closing_odds),
                "Notes": thesis,
            }
        )
        st.success("Journal entry added.")

    journal_df = pd.DataFrame(st.session_state.journal_entries)
    if journal_df.empty:
        st.info("No journal entries yet.")
    else:
        st.dataframe(journal_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download journal CSV",
            data=journal_df.to_csv(index=False).encode("utf-8"),
            file_name="mlb_bet_journal.csv",
            mime="text/csv",
        )


st.title("⚾ MLB Trading Desk")

with st.sidebar:
    selected_date = st.date_input("Game date", value=date.today()).isoformat()
    page = st.radio("Workspace", ["Home", "Pregame", "Live", "Journal"])
    refresh = st.button("Refresh MLB data")
    if refresh:
        st.cache_data.clear()

try:
    games = get_schedule(selected_date)
except Exception as exc:
    st.error(f"Could not reach MLB Stats API: {exc}")
    games = []

if page == "Home":
    render_home(games, selected_date)
elif page == "Pregame":
    render_pregame(games)
elif page == "Live":
    render_live(games)
else:
    render_journal()

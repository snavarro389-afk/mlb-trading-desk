from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from data_sources import (
    batted_ball_events,
    command_summary,
    contact_summary,
    game_label,
    get_live_feed,
    get_schedule,
    pitch_events,
    pitcher_lines,
)
from scoring import analyze_slate, market_classification, slate_frame
from strategy_packet import MarketPrice, build_strategy_packet

CURRENT_SEASON = date.today().year
st.set_page_config(page_title="MLB Trading Desk", page_icon="⚾", layout="wide")


def show_value(value, digits: int = 2):
    if value is None:
        return "N/A"
    return round(float(value), digits)


def render_dashboard(analyses: list[dict], selected_date: str, refreshed_at: str) -> None:
    st.header("Decision Dashboard")
    st.caption("Matchup intelligence plus prior-three-day bullpen availability. Scores remain decision aids, not win probabilities.")
    counts = pd.Series([row["premarket_status"] for row in analyses]).value_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Games", len(analyses))
    c2.metric("Top matchups", int(counts.get("TOP MATCHUP", 0)))
    c3.metric("Review / data checks", int(counts.get("REVIEW", 0) + counts.get("DATA CHECK", 0)))
    c4.metric("Last refresh", refreshed_at)

    if not analyses:
        st.info("No MLB games found for the selected date.")
        return

    st.subheader("Top attention candidates")
    st.dataframe(slate_frame(analyses[:5]), use_container_width=True, hide_index=True)

    incomplete = sum(row["confidence"] != "High" for row in analyses)
    if incomplete:
        st.warning(f"{incomplete} game(s) have incomplete Phase 1 data. Missing values are shown as N/A and do not create artificial edges.")

    st.info("v0.5 adds prior-three-day bullpen workload and availability. It flags rested, limited, or concerning usage without treating workload as bullpen talent. Injury context and automated odds remain future layers.")


def render_slate(analyses: list[dict]) -> None:
    st.header("Automated Slate")
    st.caption("Premarket matchup view. Use Readiness to see whether a game is ready for price review or still awaiting lineups/data.")
    if not analyses:
        st.info("No games available.")
        return

    actions = sorted({row["premarket_status"] for row in analyses})
    selected = st.multiselect("Show premarket statuses", actions, default=actions)
    filtered = [row for row in analyses if row["premarket_status"] in selected]
    st.dataframe(slate_frame(filtered), use_container_width=True, hide_index=True)

    with st.expander("How Phase 1 scoring works"):
        st.markdown(
            """
- **Matchup Separation Score** measures the size of the starter-and-season-offense difference.
- Starting pitching receives 65% of the current matchup comparison.
- Season offense baseline receives 35%.
- Missing data remains `N/A`; it is not replaced with invented averages.
- **Baseball-side advantage** is not a bet recommendation.
- **Market status** remains pending until two-sided odds are submitted.
"""
        )


def render_game_card(analyses: list[dict]) -> None:
    st.header("Game Card")
    if not analyses:
        st.info("No games available.")
        return

    labels = {row["matchup"]: row for row in analyses}
    item = labels[st.selectbox("Select matchup", list(labels), key="game_card_matchup")]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Separation score", show_value(item["separation_score"], 1))
    c2.metric("Readiness", item["readiness"])
    c3.metric("Baseball-side advantage", item["baseball_advantage"])
    c4.metric("Confidence", f"{item['confidence']} · {item['completeness']}%")

    d = item["details"]

    st.subheader("Starting pitching — season data")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Team": item["away"],
                    "Starter": item["away_starter"],
                    "Score": show_value(item["away_sp_score"], 1),
                    "ERA": show_value(d.get("Away_ERA")),
                    "WHIP": show_value(d.get("Away_WHIP")),
                    "K/9": show_value(d.get("Away_K9")),
                    "BB/9": show_value(d.get("Away_BB9")),
                },
                {
                    "Team": item["home"],
                    "Starter": item["home_starter"],
                    "Score": show_value(item["home_sp_score"], 1),
                    "ERA": show_value(d.get("Home_ERA")),
                    "WHIP": show_value(d.get("Home_WHIP")),
                    "K/9": show_value(d.get("Home_K9")),
                    "BB/9": show_value(d.get("Home_BB9")),
                },
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Offense matchup intelligence")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Team": item["away"],
                    "Season baseline": show_value(item["away_off_score"], 1),
                    f"Vs {item['home_pitch_hand']}HP": show_value(item["away_split_score"], 1),
                    "Matchup score": show_value(item["away_matchup_off_score"], 1),
                    "Recent 14": show_value(item["away_recent14_score"], 1),
                    "Recent 30": show_value(item["away_recent30_score"], 1),
                    "Trend": item["away_recent_trend"],
                    "AVG": show_value(d.get("Away_AVG"), 3),
                    "OBP": show_value(d.get("Away_OBP"), 3),
                    "SLG": show_value(d.get("Away_SLG"), 3),
                    "OPS": show_value(d.get("Away_OPS"), 3),
                    "K%": show_value(d.get("Away_K%"), 1),
                    "BB%": show_value(d.get("Away_BB%"), 1),
                },
                {
                    "Team": item["home"],
                    "Season baseline": show_value(item["home_off_score"], 1),
                    f"Vs {item['away_pitch_hand']}HP": show_value(item["home_split_score"], 1),
                    "Matchup score": show_value(item["home_matchup_off_score"], 1),
                    "Recent 14": show_value(item["home_recent14_score"], 1),
                    "Recent 30": show_value(item["home_recent30_score"], 1),
                    "Trend": item["home_recent_trend"],
                    "AVG": show_value(d.get("Home_AVG"), 3),
                    "OBP": show_value(d.get("Home_OBP"), 3),
                    "SLG": show_value(d.get("Home_SLG"), 3),
                    "OPS": show_value(d.get("Home_OPS"), 3),
                    "K%": show_value(d.get("Home_K%"), 1),
                    "BB%": show_value(d.get("Home_BB%"), 1),
                },
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Bullpen availability — prior three days")
    away_bp = item["away_bullpen"]
    home_bp = item["home_bullpen"]
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Team": item["away"],
                    "Status": away_bp["status"],
                    "Games found": away_bp["games_found"],
                    "Relief pitches": away_bp["team_pitches"],
                    "Relief appearances": away_bp["team_appearances"],
                    "Multi-day arms": away_bp["multi_day_arms"],
                    "Max reliever pitches": away_bp["max_reliever_pitches"],
                },
                {
                    "Team": item["home"],
                    "Status": home_bp["status"],
                    "Games found": home_bp["games_found"],
                    "Relief pitches": home_bp["team_pitches"],
                    "Relief appearances": home_bp["team_appearances"],
                    "Multi-day arms": home_bp["multi_day_arms"],
                    "Max reliever pitches": home_bp["max_reliever_pitches"],
                },
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.info(f"Full-game context: {item['full_game_context']}")

    with st.expander(f"{item['away']} reliever detail"):
        st.dataframe(pd.DataFrame(away_bp["relievers"]), use_container_width=True, hide_index=True)
    with st.expander(f"{item['home']} reliever detail"):
        st.dataframe(pd.DataFrame(home_bp["relievers"]), use_container_width=True, hide_index=True)

    st.subheader("Data completeness")
    availability = item["component_availability"]
    st.dataframe(
        pd.DataFrame(
            [
                {"Component": "Probable starters", "Status": "Available" if item["away_starter"] != "TBD" and item["home_starter"] != "TBD" else "Pending"},
                {"Component": "Away starter season stats", "Status": "Available" if availability["away_starter"] else "Missing"},
                {"Component": "Home starter season stats", "Status": "Available" if availability["home_starter"] else "Missing"},
                {"Component": "Away season offense", "Status": "Available" if availability["away_offense"] else "Missing"},
                {"Component": "Home season offense", "Status": "Available" if availability["home_offense"] else "Missing"},
                {"Component": "Starter handedness", "Status": f"{item['away_starter']}: {item['away_pitch_hand']} | {item['home_starter']}: {item['home_pitch_hand']}"},
                {"Component": "Offense handedness splits", "Status": "Available" if item["component_availability"]["away_split"] and item["component_availability"]["home_split"] else "Partial / missing"},
                {"Component": "Confirmed lineups", "Status": f"{item['lineup_status']} ({item['away_lineup_count']}/{item['home_lineup_count']})"},
                {"Component": "Bullpen workload", "Status": f"{item['away']}: {item['away_bullpen']['status']} | {item['home']}: {item['home_bullpen']['status']}"},
                {"Component": "Sportsbook odds", "Status": "Manual submission below"},
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Market input and strategy handoff")
    market = st.selectbox(
        "Market",
        ["Full-game ML", "F5 ML", "F5 -0.5", "Run line", "Total", "Live only"],
        key=f"market-{item['game_pk']}",
    )
    submit_key = f"market-submitted-{item['game_pk']}"
    st.session_state.setdefault(submit_key, False)

    with st.form(f"market-form-{item['game_pk']}"):
        m1, m2 = st.columns(2)
        with m1:
            away_odds = st.number_input(
                f"{item['away']} odds",
                value=-110,
                step=1,
                key=f"away-{item['game_pk']}",
            )
        with m2:
            home_odds = st.number_input(
                f"{item['home']} odds",
                value=-110,
                step=1,
                key=f"home-{item['game_pk']}",
            )
        submitted = st.form_submit_button("Submit current market", type="primary")

    if submitted:
        st.session_state[submit_key] = True

    notes = st.text_area(
        "Optional context not yet automated",
        placeholder="Paste lineup changes, alternate markets, injury news, or screenshot observations.",
        key=f"notes-{item['game_pk']}",
    )

    odds_submitted = bool(st.session_state[submit_key])
    final_market_status = market_classification(
        item["premarket_status"],
        item["confidence"],
        odds_submitted,
        notes_present=bool(notes.strip()),
    )

    if odds_submitted:
        away_raw = MarketPrice(int(away_odds)).implied_probability
        home_raw = MarketPrice(int(home_odds)).implied_probability
        total = away_raw + home_raw
        v1, v2, v3, v4 = st.columns(4)
        v1.metric(f"{item['away']} no-vig", f"{away_raw / total:.1%}")
        v2.metric(f"{item['home']} no-vig", f"{home_raw / total:.1%}")
        v3.metric("Market hold", f"{total - 1:.1%}")
        v4.metric("Market status", final_market_status)
        packet_away, packet_home = int(away_odds), int(home_odds)
    else:
        st.warning("Market value is unknown. Submit current two-sided odds before using the market classification.")
        packet_away, packet_home = None, None

    packet = build_strategy_packet(
        item,
        market,
        packet_away,
        packet_home,
        notes,
        final_market_status,
    )
    st.text_area("Copy into the Betting Strategy thread", value=packet, height=500)
    st.download_button(
        "Download strategy packet",
        packet.encode("utf-8"),
        f"strategy_packet_{item['game_pk']}.txt",
        "text/plain",
    )

    if item["errors"]:
        with st.expander("Data retrieval warnings"):
            for error in item["errors"]:
                st.write(f"- {error}")


def render_live(games: list[dict]) -> None:
    st.header("Live Desk")
    st.caption("Automated game state, command, velocity, and contact monitoring. Trigger logic remains a future layer.")
    if not games:
        st.info("No games found.")
        return

    labels = {game_label(game): game.get("gamePk") for game in games}
    choice = st.selectbox("Select live game", list(labels), key="live_game")
    try:
        feed = get_live_feed(int(labels[choice]))
    except Exception as exc:
        st.error(f"Could not retrieve live game feed: {exc}")
        return

    game_data, live_data = feed.get("gameData", {}), feed.get("liveData", {})
    linescore = live_data.get("linescore", {})
    away = game_data.get("teams", {}).get("away", {}).get("name", "Away")
    home = game_data.get("teams", {}).get("home", {}).get("name", "Home")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(away, linescore.get("teams", {}).get("away", {}).get("runs", 0))
    c2.metric(home, linescore.get("teams", {}).get("home", {}).get("runs", 0))
    c3.metric("Game state", f"{linescore.get('inningState', '')} {linescore.get('currentInning', '')}".strip())
    c4.metric("Status", game_data.get("status", {}).get("detailedState", ""))

    pitchers = pitcher_lines(feed)
    pitches = pitch_events(feed)
    bbe = batted_ball_events(feed)

    st.subheader("Pitching line")
    st.dataframe(pitchers, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Command and velocity")
        st.dataframe(command_summary(pitches), use_container_width=True, hide_index=True)
    with right:
        st.subheader("Contact allowed")
        st.dataframe(contact_summary(bbe), use_container_width=True, hide_index=True)

    with st.expander("Batted-ball events"):
        st.dataframe(bbe, use_container_width=True, hide_index=True)
    with st.expander("Pitch-by-pitch events"):
        st.dataframe(pitches, use_container_width=True, hide_index=True)


def render_journal() -> None:
    st.header("Journal")
    st.caption("Session-based for now. Persistent storage and automatic Game Card prefilling are later phases.")
    st.session_state.setdefault("journal_entries", [])

    c1, c2, c3 = st.columns(3)
    with c1:
        entry_date = st.date_input("Date", value=date.today(), key="journal_date")
        game = st.text_input("Game", placeholder="Mets at Phillies")
        market = st.selectbox(
            "Market",
            ["Full-game ML", "F5 ML", "F5 -0.5", "Run line", "Total", "No bet / tracked pass"],
        )
    with c2:
        selection = st.text_input("Selection", placeholder="Phillies F5 -0.5")
        odds = st.number_input("Entry odds", value=-110, step=1)
        stake = st.number_input("Stake", min_value=0.0, value=5.0, step=1.0)
    with c3:
        classification = st.selectbox(
            "Decision status",
            ["VALUE CANDIDATE", "PRICE SENSITIVE", "LIVE WATCH", "PASS", "DATA CHECK", "NO BET"],
        )
        result = st.selectbox("Result", ["Open", "Win", "Loss", "Push", "No bet"])
        closing = st.number_input("Closing odds", value=-110, step=1)

    notes = st.text_area("Thesis, execution, and postgame lesson")
    if st.button("Add journal entry", type="primary"):
        st.session_state.journal_entries.append(
            {
                "Date": entry_date.isoformat(),
                "Game": game,
                "Market": market,
                "Selection": selection,
                "Entry Odds": int(odds),
                "Stake": float(stake),
                "Decision Status": classification,
                "Result": result,
                "Closing Odds": int(closing),
                "Notes": notes,
            }
        )
        st.success("Journal entry added.")

    frame = pd.DataFrame(st.session_state.journal_entries)
    if frame.empty:
        st.info("No journal entries yet.")
    else:
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.download_button(
            "Download journal CSV",
            frame.to_csv(index=False).encode("utf-8"),
            "mlb_bet_journal.csv",
            "text/csv",
        )


st.title("⚾ MLB Trading Desk v0.5")
with st.sidebar:
    selected_date = st.date_input("Game date", value=date.today()).isoformat()
    page = st.radio("Workspace", ["Dashboard", "Slate", "Game Card", "Live Desk", "Journal"])
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = datetime.now().strftime("%-I:%M %p")
    if st.button("Refresh MLB data"):
        st.cache_data.clear()
        st.session_state.last_refresh = datetime.now().strftime("%-I:%M %p")

try:
    games = get_schedule(selected_date)
except Exception as exc:
    st.error(f"Could not reach MLB Stats API: {exc}")
    games = []

analyses = analyze_slate(games, CURRENT_SEASON, selected_date) if page in {"Dashboard", "Slate", "Game Card"} and games else []

if page == "Dashboard":
    render_dashboard(analyses, selected_date, st.session_state.last_refresh)
elif page == "Slate":
    render_slate(analyses)
elif page == "Game Card":
    render_game_card(analyses)
elif page == "Live Desk":
    render_live(games)
else:
    render_journal()

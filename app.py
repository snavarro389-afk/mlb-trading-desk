from __future__ import annotations

from datetime import date

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
from scoring import analyze_slate, slate_frame
from strategy_packet import MarketPrice, build_strategy_packet

CURRENT_SEASON = date.today().year
st.set_page_config(page_title="MLB Trading Desk", page_icon="⚾", layout="wide")


def render_dashboard(analyses: list[dict], selected_date: str) -> None:
    st.header("Decision Dashboard")
    st.caption("Automated research triage. Scores rank where to look; they are not win probabilities.")
    counts = pd.Series([row["classification"] for row in analyses]).value_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Games", len(analyses))
    c2.metric("Deep dives", int(counts.get("DEEP DIVE", 0)))
    c3.metric("Price / live watches", int(counts.get("PRICE CHECK", 0) + counts.get("LIVE WATCH", 0)))
    c4.metric("Date", selected_date)
    if not analyses:
        st.info("No MLB games found for the selected date.")
        return
    st.subheader("Top attention candidates")
    st.dataframe(slate_frame(analyses[:5]), use_container_width=True, hide_index=True)
    incomplete = sum(row["confidence"] != "High" for row in analyses)
    if incomplete:
        st.warning(f"{incomplete} game(s) have incomplete starter or offense data. Their ranking is downgraded.")
    st.info("Phase 1 automates the slate, probable starters, season starter stats, team offense, research ranking, market math, and the Strategy Packet. Bullpen workload, confirmed lineups, injuries, and automated sportsbook odds remain upcoming layers.")


def render_slate(analyses: list[dict]) -> None:
    st.header("Automated Slate")
    st.caption("Review the entire day without completing manual research checklists.")
    if not analyses:
        st.info("No games available.")
        return
    actions = sorted({row["classification"] for row in analyses})
    selected = st.multiselect("Show actions", actions, default=actions)
    st.dataframe(slate_frame([row for row in analyses if row["classification"] in selected]), use_container_width=True, hide_index=True)
    with st.expander("How Phase 1 scoring works"):
        st.markdown("""
- Starting pitching receives 65% of the current matchup comparison.
- Team offense receives 35%.
- Larger measurable separation raises the Research Priority Score.
- Missing data lowers confidence and caps the score.
- This is a research-priority score, not a projected win probability.
""")


def render_game_card(analyses: list[dict]) -> None:
    st.header("Game Card")
    if not analyses:
        st.info("No games available.")
        return
    labels = {row["matchup"]: row for row in analyses}
    item = labels[st.selectbox("Select matchup", list(labels), key="game_card_matchup")]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Research score", item["research_score"])
    c2.metric("Next action", item["classification"])
    c3.metric("Preliminary lean", item["lean"])
    c4.metric("Confidence", f"{item['confidence']} · {item['completeness']}%")

    d = item["details"]
    st.subheader("Starting pitching")
    st.dataframe(pd.DataFrame([
        {"Team": item["away"], "Starter": item["away_starter"], "Score": item["away_sp_score"], "ERA": d.get("Away_ERA"), "WHIP": d.get("Away_WHIP"), "K/9": d.get("Away_K9"), "BB/9": d.get("Away_BB9")},
        {"Team": item["home"], "Starter": item["home_starter"], "Score": item["home_sp_score"], "ERA": d.get("Home_ERA"), "WHIP": d.get("Home_WHIP"), "K/9": d.get("Home_K9"), "BB/9": d.get("Home_BB9")},
    ]), use_container_width=True, hide_index=True)

    st.subheader("Team offense")
    st.dataframe(pd.DataFrame([
        {"Team": item["away"], "Score": item["away_off_score"], "AVG": d.get("Away_AVG"), "OBP": d.get("Away_OBP"), "SLG": d.get("Away_SLG"), "OPS": d.get("Away_OPS"), "K%": d.get("Away_K%"), "BB%": d.get("Away_BB%")},
        {"Team": item["home"], "Score": item["home_off_score"], "AVG": d.get("Home_AVG"), "OBP": d.get("Home_OBP"), "SLG": d.get("Home_SLG"), "OPS": d.get("Home_OPS"), "K%": d.get("Home_K%"), "BB%": d.get("Home_BB%")},
    ]), use_container_width=True, hide_index=True)

    st.subheader("Data completeness")
    datasets = item["datasets"]
    st.dataframe(pd.DataFrame([
        {"Component": "Probable starters", "Status": "Available" if item["away_starter"] != "TBD" and item["home_starter"] != "TBD" else "Pending"},
        {"Component": "Starter season stats", "Status": "Available" if datasets["aps"] and datasets["hps"] else "Partial / missing"},
        {"Component": "Team offense", "Status": "Available" if datasets["ahs"] and datasets["hhs"] else "Partial / missing"},
        {"Component": "Confirmed lineups", "Status": item["lineup_status"]},
        {"Component": "Bullpen workload", "Status": item["bullpen_status"]},
        {"Component": "Sportsbook odds", "Status": "Manual entry below"},
    ]), use_container_width=True, hide_index=True)

    st.subheader("Market input and strategy handoff")
    m1, m2, m3 = st.columns(3)
    with m1:
        market = st.selectbox("Market", ["Full-game ML", "F5 ML", "F5 -0.5", "Run line", "Total", "Live only"])
    with m2:
        away_odds = st.number_input(f"{item['away']} odds", value=-110, step=1, key=f"away-{item['game_pk']}")
    with m3:
        home_odds = st.number_input(f"{item['home']} odds", value=-110, step=1, key=f"home-{item['game_pk']}")
    away_raw, home_raw = MarketPrice(int(away_odds)).implied_probability, MarketPrice(int(home_odds)).implied_probability
    total = away_raw + home_raw
    v1, v2, v3 = st.columns(3)
    v1.metric(f"{item['away']} no-vig", f"{away_raw / total:.1%}")
    v2.metric(f"{item['home']} no-vig", f"{home_raw / total:.1%}")
    v3.metric("Market hold", f"{total - 1:.1%}")
    notes = st.text_area("Optional context not yet automated", placeholder="Paste lineup changes, alternate markets, injury news, or screenshot observations.", key=f"notes-{item['game_pk']}")
    packet = build_strategy_packet(item, market, int(away_odds), int(home_odds), notes)
    st.text_area("Copy into the Betting Strategy thread", value=packet, height=480)
    st.download_button("Download strategy packet", packet.encode("utf-8"), f"strategy_packet_{item['game_pk']}.txt", "text/plain")
    if item["errors"]:
        with st.expander("Data retrieval warnings"):
            for error in item["errors"]:
                st.write(f"- {error}")


def render_live(games: list[dict]) -> None:
    st.header("Live Desk")
    st.caption("Automated game state, command, velocity, and contact monitoring. Sportsbook prices remain manual.")
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
    away, home = game_data.get("teams", {}).get("away", {}).get("name", "Away"), game_data.get("teams", {}).get("home", {}).get("name", "Home")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(away, linescore.get("teams", {}).get("away", {}).get("runs", 0))
    c2.metric(home, linescore.get("teams", {}).get("home", {}).get("runs", 0))
    c3.metric("Game state", f"{linescore.get('inningState', '')} {linescore.get('currentInning', '')}".strip())
    c4.metric("Status", game_data.get("status", {}).get("detailedState", ""))
    pitchers, pitches, bbe = pitcher_lines(feed), pitch_events(feed), batted_ball_events(feed)
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
    st.caption("Session-based for now. Persistent storage and validation analytics are Phase 5.")
    st.session_state.setdefault("journal_entries", [])
    c1, c2, c3 = st.columns(3)
    with c1:
        entry_date = st.date_input("Date", value=date.today(), key="journal_date")
        game = st.text_input("Game", placeholder="Mets at Phillies")
        market = st.selectbox("Market", ["Full-game ML", "F5 ML", "F5 -0.5", "Run line", "Total", "No bet / tracked pass"])
    with c2:
        selection = st.text_input("Selection", placeholder="Phillies F5 -0.5")
        odds = st.number_input("Entry odds", value=-110, step=1)
        stake = st.number_input("Stake", min_value=0.0, value=5.0, step=1.0)
    with c3:
        classification = st.selectbox("App classification", ["DEEP DIVE", "PRICE CHECK", "LIVE WATCH", "PASS", "DATA CHECK"])
        result = st.selectbox("Result", ["Open", "Win", "Loss", "Push", "No bet"])
        closing = st.number_input("Closing odds", value=-110, step=1)
    notes = st.text_area("Thesis, execution, and postgame lesson")
    if st.button("Add journal entry", type="primary"):
        st.session_state.journal_entries.append({"Date": entry_date.isoformat(), "Game": game, "Market": market, "Selection": selection, "Entry Odds": int(odds), "Stake": float(stake), "Classification": classification, "Result": result, "Closing Odds": int(closing), "Notes": notes})
        st.success("Journal entry added.")
    frame = pd.DataFrame(st.session_state.journal_entries)
    if frame.empty:
        st.info("No journal entries yet.")
    else:
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.download_button("Download journal CSV", frame.to_csv(index=False).encode("utf-8"), "mlb_bet_journal.csv", "text/csv")


st.title("⚾ MLB Trading Desk")
with st.sidebar:
    selected_date = st.date_input("Game date", value=date.today()).isoformat()
    page = st.radio("Workspace", ["Dashboard", "Slate", "Game Card", "Live Desk", "Journal"])
    if st.button("Refresh MLB data"):
        st.cache_data.clear()

try:
    games = get_schedule(selected_date)
except Exception as exc:
    st.error(f"Could not reach MLB Stats API: {exc}")
    games = []

analyses = analyze_slate(games, CURRENT_SEASON) if page in {"Dashboard", "Slate", "Game Card"} and games else []
if page == "Dashboard": render_dashboard(analyses, selected_date)
elif page == "Slate": render_slate(analyses)
elif page == "Game Card": render_game_card(analyses)
elif page == "Live Desk": render_live(games)
else: render_journal()

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
from strategy_packet import build_strategy_packet
from market_engine import classify_decision, no_vig_probabilities
from storage import (
    database_status,
    load_bets,
    load_decisions,
    load_reviews,
    load_snapshots,
    register_model_version,
    save_bet,
    save_bet_review,
    save_market_snapshot,
    save_research_decision,
    update_bet_result,
)

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

    st.subheader("Market Workspace")
    st.caption(
        "The app compares the current sportsbook price with your preferred and maximum acceptable prices. "
        "It does not convert the matchup score into a win probability."
    )

    market = st.selectbox(
        "Market",
        ["Full-game ML", "F5 ML", "F5 -0.5", "Run line", "Total", "Player prop", "Live only"],
        key=f"market-{item['game_pk']}",
    )
    sportsbook = st.selectbox(
        "Sportsbook",
        ["DraftKings", "FanDuel", "BetMGM", "Caesars", "Other"],
        key=f"sportsbook-{item['game_pk']}",
    )

    with st.form(f"market-form-{item['game_pk']}"):
        m1, m2 = st.columns(2)
        with m1:
            away_odds = st.number_input(f"{item['away']} odds", value=-110, step=1)
        with m2:
            home_odds = st.number_input(f"{item['home']} odds", value=-110, step=1)
        submitted = st.form_submit_button("Analyze current market", type="primary")

    state_key = f"market-state-{item['game_pk']}"
    if submitted:
        st.session_state[state_key] = {"away": int(away_odds), "home": int(home_odds)}

    odds_state = st.session_state.get(state_key)
    notes = st.text_area(
        "Context or thesis notes",
        placeholder="Lineup news, market movement, injury context, or reasons the price target was chosen.",
        key=f"notes-{item['game_pk']}",
    )

    if not odds_state:
        st.warning("Submit a two-sided market before evaluating a price decision.")
    else:
        away_odds = int(odds_state["away"])
        home_odds = int(odds_state["home"])
        try:
            away_nv, home_nv, hold = no_vig_probabilities(away_odds, home_odds)
        except ValueError as exc:
            st.error(str(exc))
            return

        v1, v2, v3, v4 = st.columns(4)
        v1.metric(f"{item['away']} no-vig", f"{away_nv:.1%}")
        v2.metric(f"{item['home']} no-vig", f"{home_nv:.1%}")
        v3.metric("Sportsbook hold", f"{hold:.1%}")
        v4.metric("Research lean", item["baseball_advantage"])
        st.caption("No-vig probability describes the current market consensus after removing hold; it is not the model's fair probability.")

        selection = st.selectbox(
            "Side being evaluated",
            [item["away"], item["home"]],
            index=0 if item["baseball_advantage"] == item["away"] else 1,
            key=f"decision-selection-{item['game_pk']}",
        )
        selected_odds = away_odds if selection == item["away"] else home_odds
        opposing_odds = home_odds if selection == item["away"] else away_odds
        selected_no_vig = away_nv if selection == item["away"] else home_nv

        p1, p2 = st.columns(2)
        with p1:
            target_odds = st.number_input(
                "Preferred target price",
                value=int(selected_odds),
                step=1,
                key=f"target-{item['game_pk']}-{selection}",
                help="The price you would prefer to receive. Example: -135.",
            )
        with p2:
            maximum_odds = st.number_input(
                "Maximum acceptable price",
                value=int(selected_odds - 5),
                step=1,
                key=f"maximum-{item['game_pk']}-{selection}",
                help="The worst price you would still consider. Example: -140. A larger number is always a better bettor price.",
            )

        final_action = st.selectbox(
            "Final action",
            ["UNDECIDED", "WAIT", "PASS", "BET PLACED"],
            key=f"final-action-{item['game_pk']}",
        )

        try:
            decision = classify_decision(
                selection=selection,
                research_lean=item["baseball_advantage"],
                confidence=item["confidence"],
                readiness=item["readiness"],
                current_odds=int(selected_odds),
                target_odds=int(target_odds),
                maximum_odds=int(maximum_odds),
            )
        except ValueError as exc:
            st.error(str(exc))
            decision = None

        if decision:
            d1, d2, d3 = st.columns(3)
            d1.metric("Recommendation", decision.recommendation)
            d2.metric("Price status", decision.price_status)
            d3.metric("Lifecycle", decision.lifecycle_status)
            st.info(decision.rationale)

            snapshot_id = st.session_state.get(f"latest-snapshot-{item['game_pk']}")
            a1, a2 = st.columns(2)
            with a1:
                if st.button("Save market snapshot", key=f"save-snapshot-{item['game_pk']}"):
                    try:
                        snapshot_id = save_market_snapshot(
                            item=item,
                            game_date=selected_date,
                            market_type=market,
                            selection=selection,
                            selection_odds=int(selected_odds),
                            opposing_odds=int(opposing_odds),
                            no_vig_probability=float(selected_no_vig),
                            market_status=decision.recommendation,
                            notes=notes,
                            sportsbook=sportsbook,
                        )
                        st.session_state[f"latest-snapshot-{item['game_pk']}"] = snapshot_id
                        st.session_state["latest_snapshot_id"] = snapshot_id
                        st.success("Market snapshot saved to Supabase.")
                    except Exception as exc:
                        st.error(f"Could not save snapshot: {exc}")
            with a2:
                if st.button("Save decision evaluation", type="primary", key=f"save-decision-{item['game_pk']}"):
                    try:
                        decision_id = save_research_decision(
                            snapshot_id=snapshot_id,
                            item=item,
                            game_date=selected_date,
                            sportsbook=sportsbook,
                            market_type=market,
                            selection=selection,
                            current_odds=int(selected_odds),
                            opposing_odds=int(opposing_odds),
                            no_vig_probability=float(selected_no_vig),
                            market_hold=float(hold),
                            target_odds=int(target_odds),
                            maximum_odds=int(maximum_odds),
                            recommendation=decision.recommendation,
                            lifecycle_status=decision.lifecycle_status,
                            price_status=decision.price_status,
                            final_action=final_action,
                            rationale=decision.rationale,
                            notes=notes,
                        )
                        st.success(f"Decision evaluation saved. ID: {decision_id}")
                    except Exception as exc:
                        st.error(f"Could not save decision: {exc}")

            packet = build_strategy_packet(
                item, market, away_odds, home_odds, notes, decision.recommendation
            )
            packet += (
                f"\n\nMARKET WORKSPACE\n"
                f"Sportsbook: {sportsbook}\n"
                f"Evaluated selection: {selection} {selected_odds:+d}\n"
                f"No-vig market probability: {selected_no_vig:.1%}\n"
                f"Target price: {int(target_odds):+d}\n"
                f"Maximum acceptable: {int(maximum_odds):+d}\n"
                f"Recommendation: {decision.recommendation}\n"
                f"Final action: {final_action}\n"
                f"Rationale: {decision.rationale}"
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
    st.header("Persistent Journal")
    status, message = database_status()
    if status != "CONNECTED":
        st.error("Supabase is not connected. Complete the setup instructions before saving journal data.")
        st.caption(message)
        return

    tabs = st.tabs(["New bet", "Settle bet", "Review bet", "Stored bets", "Market snapshots", "Decision history"])

    with tabs[0]:
        c1, c2, c3 = st.columns(3)
        with c1:
            entry_date = st.date_input("Date", value=date.today(), key="db_journal_date")
            game_pk = st.number_input("MLB game ID (optional)", min_value=0, value=0, step=1)
            market = st.selectbox(
                "Market",
                ["Full-game ML", "F5 ML", "F5 -0.5", "Run line", "Total", "Player prop"],
                key="db_market",
            )
        with c2:
            selection = st.text_input("Selection", placeholder="Phillies F5 -0.5", key="db_selection")
            odds = st.number_input("Entry odds", value=-110, step=1, key="db_odds")
            stake = st.number_input("Stake", min_value=0.0, value=5.0, step=1.0, key="db_stake")
        with c3:
            decision_status = st.selectbox(
                "Decision status",
                ["VALUE CANDIDATE", "PRICE SENSITIVE", "LIVE WATCH", "MANUAL BET"],
                key="db_status",
            )
            snapshot_id = st.text_input(
                "Snapshot ID (optional)",
                value=st.session_state.get("latest_snapshot_id", ""),
                key="db_snapshot",
            )
        notes = st.text_area("Thesis and entry context", key="db_notes")

        if st.button("Save bet to Supabase", type="primary"):
            if not selection.strip():
                st.error("Selection is required.")
            else:
                try:
                    bet_id = save_bet(
                        snapshot_id=snapshot_id.strip() or None,
                        game_pk=int(game_pk) if game_pk else None,
                        game_date=entry_date.isoformat(),
                        market_type=market,
                        selection=selection.strip(),
                        entry_odds=int(odds),
                        stake=float(stake),
                        decision_status=decision_status,
                        notes=notes,
                    )
                    st.success(f"Bet saved. ID: {bet_id}")
                except Exception as exc:
                    st.error(f"Could not save bet: {exc}")

    bets = load_bets()

    with tabs[1]:
        if bets.empty:
            st.info("No stored bets.")
        else:
            labels = {
                f"{row.get('placed_at', '')} | {row.get('selection', '')} | {row.get('entry_odds', '')} | {row.get('result', '')}": row["bet_id"]
                for _, row in bets.iterrows()
            }
            label = st.selectbox("Choose bet", list(labels), key="settle_bet")
            result = st.selectbox("Result", ["Open", "Win", "Loss", "Push", "Void"], key="settle_result")
            profit_loss = st.number_input("Profit / loss", value=0.0, step=1.0, key="settle_pl")
            closing_odds = st.number_input("Closing odds", value=-110, step=1, key="settle_close")
            if st.button("Update bet result"):
                try:
                    update_bet_result(labels[label], result, float(profit_loss), int(closing_odds))
                    st.success("Bet updated.")
                except Exception as exc:
                    st.error(f"Could not update bet: {exc}")

    with tabs[2]:
        if bets.empty:
            st.info("No stored bets.")
        else:
            labels = {
                f"{row.get('game_date', '')} | {row.get('selection', '')} | {row.get('result', '')}": row["bet_id"]
                for _, row in bets.iterrows()
            }
            label = st.selectbox("Choose bet to review", list(labels), key="review_bet")
            thesis = st.text_area("Original thesis", key="review_thesis")
            thesis_killers = st.text_area("Thesis killers / cancellation conditions", key="review_killers")
            thesis_broken = st.checkbox("Thesis broke during the game", key="review_broken")
            c1, c2 = st.columns(2)
            with c1:
                execution_grade = st.selectbox("Execution grade", ["A", "B", "C", "D", "F"], key="exec_grade")
            with c2:
                thesis_grade = st.selectbox("Thesis grade", ["A", "B", "C", "D", "F"], key="thesis_grade")
            lesson = st.text_area("Postgame lesson", key="review_lesson")
            if st.button("Save review"):
                try:
                    save_bet_review(
                        labels[label], thesis, thesis_killers, thesis_broken,
                        execution_grade, thesis_grade, lesson,
                    )
                    st.success("Review saved.")
                except Exception as exc:
                    st.error(f"Could not save review: {exc}")

    with tabs[3]:
        bets = load_bets()
        if bets.empty:
            st.info("No stored bets.")
        else:
            st.dataframe(bets, use_container_width=True, hide_index=True)
            st.download_button(
                "Download bets CSV",
                bets.to_csv(index=False).encode("utf-8"),
                "mlb_bets_backup.csv",
                "text/csv",
            )
        reviews = load_reviews()
        if not reviews.empty:
            st.subheader("Stored reviews")
            st.dataframe(reviews, use_container_width=True, hide_index=True)

    with tabs[4]:
        snapshots = load_snapshots()
        if snapshots.empty:
            st.info("No market snapshots saved yet.")
        else:
            st.dataframe(snapshots, use_container_width=True, hide_index=True)
            st.download_button(
                "Download snapshots CSV",
                snapshots.to_csv(index=False).encode("utf-8"),
                "mlb_market_snapshots_backup.csv",
                "text/csv",
            )


    with tabs[5]:
        decisions = load_decisions()
        if decisions.empty:
            st.info("No decision evaluations saved yet.")
        else:
            st.dataframe(decisions, use_container_width=True, hide_index=True)
            st.download_button(
                "Download decisions CSV",
                decisions.to_csv(index=False).encode("utf-8"),
                "mlb_research_decisions_backup.csv",
                "text/csv",
            )


st.title("⚾ MLB Trading Desk v0.6")
with st.sidebar:
    selected_date = st.date_input("Game date", value=date.today()).isoformat()
    page = st.radio("Workspace", ["Dashboard", "Slate", "Game Card", "Live Desk", "Journal"])
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = datetime.now().strftime("%-I:%M %p")
    if st.button("Refresh MLB data"):
        st.cache_data.clear()
        st.session_state.last_refresh = datetime.now().strftime("%-I:%M %p")

    db_state, db_message = database_status()
    if db_state == "CONNECTED":
        st.success("Database: Connected")
        try:
            register_model_version()
        except Exception:
            pass
    elif db_state == "NOT CONFIGURED":
        st.warning("Database: Not configured")
    else:
        st.error(f"Database: {db_state}")
    with st.expander("Database details"):
        st.write(db_message)

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

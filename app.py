from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st

from data_sources import (
    batted_ball_events,
    command_summary,
    contact_summary,
    extract_live_thesis_inputs,
    game_label,
    get_live_feed,
    get_schedule,
    pitch_events,
    pitcher_lines,
)
from live_engine import (
    FEED_CONFLICT,
    FEED_CURRENT,
    FEED_STALE,
    evaluate_live_thesis,
)
from market_engine import classify_decision, no_vig_probabilities
from scoring import analyze_slate, slate_frame
from storage import (
    database_status,
    get_latest_live_thesis_snapshot,
    get_latest_research_decision,
    get_live_thesis_snapshots,
    load_bets,
    load_decisions,
    load_live_thesis_snapshots,
    load_reviews,
    load_snapshots,
    register_model_version,
    save_bet,
    save_bet_review,
    save_live_thesis_snapshot,
    save_market_snapshot,
    save_research_decision,
    update_bet_result,
)
from strategy_packet import build_strategy_packet


CURRENT_SEASON = date.today().year

st.set_page_config(
    page_title="MLB Trading Desk",
    page_icon="⚾",
    layout="wide",
)


def show_value(value: Any, digits: int = 2) -> str | float:
    if value is None:
        return "N/A"

    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return "N/A"


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def display_signed_odds(value: Any) -> str:
    try:
        return f"{int(value):+d}"
    except (TypeError, ValueError):
        return "N/A"


def decision_team(
    decision: dict[str, Any],
    away_team: str,
    home_team: str,
) -> str | None:
    selection = str(decision.get("selection") or "").strip()

    if selection == away_team:
        return away_team

    if selection == home_team:
        return home_team

    return None


def bullpen_default_index(status: str | None) -> int:
    options = [
        "UNKNOWN",
        "FULLY AVAILABLE",
        "MOSTLY AVAILABLE",
        "LIMITED",
        "COMPROMISED",
    ]

    normalized = str(status or "UNKNOWN").strip().upper()

    if normalized in options:
        return options.index(normalized)

    return 0


LIVE_AUTO_FIELD_KEYS = {
    "tracked_pitcher_name": "live-pitcher-name-{game_pk}",
    "tracked_pitcher_id": "live-pitcher-id-{game_pk}",
    "pitch_count": "live-pitch-count-{game_pk}",
    "strikes": "live-strikes-{game_pk}",
    "pitcher_walks": "live-pitcher-walks-{game_pk}",
    "batters_faced": "live-batters-faced-{game_pk}",
    "pitcher_strikeouts": "live-pitcher-strikeouts-{game_pk}",
    "favored_starter_still_active": "live-starter-active-{game_pk}",
    "pitcher_hard_hits_allowed": "live-hard-hits-allowed-{game_pk}",
    "pitcher_barrels_allowed": "live-barrels-allowed-{game_pk}",
    "balls_in_play_against_pitcher": "live-bip-against-{game_pk}",
    "favored_plate_appearances": "live-offense-pa-{game_pk}",
    "favored_hard_hits": "live-offense-hard-hits-{game_pk}",
    "favored_barrels": "live-offense-barrels-{game_pk}",
    "favored_walks": "live-offense-walks-{game_pk}",
    "favored_strikeouts": "live-offense-strikeouts-{game_pk}",
    "favored_pitches_seen": "live-offense-pitches-seen-{game_pk}",
}


def live_feed_signature(inputs: dict[str, Any]) -> tuple[Any, ...]:
    """Return a compact signature that changes only when meaningful live data changes."""
    fields = (
        "inning",
        "inning_half",
        "outs",
        "away_score",
        "home_score",
        "runner_on_first",
        "runner_on_second",
        "runner_on_third",
        "current_pitcher_id",
        "tracked_pitcher_id",
        "pitch_count",
        "strikes",
        "pitcher_walks",
        "pitcher_strikeouts",
        "batters_faced",
        "pitcher_hard_hits_allowed",
        "pitcher_barrels_allowed",
        "favored_plate_appearances",
        "favored_hard_hits",
        "favored_barrels",
        "favored_walks",
        "favored_strikeouts",
        "favored_pitches_seen",
        "favored_starter_still_active",
    )
    return tuple(inputs.get(field) for field in fields)


def sync_live_widget_state(
    game_pk: int,
    auto_inputs: dict[str, Any],
) -> bool:
    """Sync MLB-fed values into widgets only when the feed changes.

    Live odds and qualitative bullpen controls are intentionally excluded.
    A user can freeze the statistical widgets with the manual-override lock.
    """
    signature = live_feed_signature(auto_inputs)
    signature_key = f"live-auto-signature-{game_pk}"
    locked = bool(
        st.session_state.get(
            f"live-manual-stat-lock-{game_pk}",
            False,
        )
    )

    if locked or st.session_state.get(signature_key) == signature:
        return False

    for source_field, widget_pattern in LIVE_AUTO_FIELD_KEYS.items():
        value = auto_inputs.get(source_field)
        widget_key = widget_pattern.format(game_pk=game_pk)

        if source_field == "tracked_pitcher_name":
            st.session_state[widget_key] = str(value or "")
        elif source_field == "favored_starter_still_active":
            st.session_state[widget_key] = bool(value)
        else:
            st.session_state[widget_key] = safe_int(value)

    first_pitch_rate = auto_inputs.get("first_pitch_strike_rate")
    st.session_state[f"live-first-pitch-strike-{game_pk}"] = round(
        safe_float(first_pitch_rate) * 100,
        1,
    )
    st.session_state[signature_key] = signature
    st.session_state[f"live-last-data-change-{game_pk}"] = (
        datetime.now().astimezone().isoformat(timespec="seconds")
    )
    return True


def feed_source_timestamp(feed: dict[str, Any]) -> str:
    metadata = feed.get("metaData", {})
    timestamp = metadata.get("timeStamp")
    if timestamp:
        return str(timestamp)

    current_play = (
        feed.get("liveData", {})
        .get("plays", {})
        .get("currentPlay", {})
    )
    about = current_play.get("about", {})
    return str(about.get("endTime") or about.get("startTime") or "N/A")


def render_dashboard(
    analyses: list[dict[str, Any]],
    selected_date: str,
    refreshed_at: str,
) -> None:
    st.header("Decision Dashboard")
    st.caption(
        "Matchup intelligence plus prior-three-day bullpen availability. "
        "Scores remain decision aids, not win probabilities."
    )

    counts = pd.Series(
        [row["premarket_status"] for row in analyses]
    ).value_counts()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Games", len(analyses))
    c2.metric(
        "Top matchups",
        int(counts.get("TOP MATCHUP", 0)),
    )
    c3.metric(
        "Review / data checks",
        int(
            counts.get("REVIEW", 0)
            + counts.get("DATA CHECK", 0)
        ),
    )
    c4.metric("Last refresh", refreshed_at)

    if not analyses:
        st.info("No MLB games found for the selected date.")
        return

    st.subheader("Top attention candidates")
    st.dataframe(
        slate_frame(analyses[:5]),
        use_container_width=True,
        hide_index=True,
    )

    incomplete = sum(
        row["confidence"] != "High"
        for row in analyses
    )

    if incomplete:
        st.warning(
            f"{incomplete} game(s) have incomplete Phase 1 data. "
            "Missing values are shown as N/A and do not create artificial edges."
        )

    st.info(
        "v0.7 retains the pregame matchup and market workflow while adding "
        "a separate Live Thesis Engine. Live thesis health is not a win probability."
    )


def render_slate(
    analyses: list[dict[str, Any]],
) -> None:
    st.header("Automated Slate")
    st.caption(
        "Premarket matchup view. Use Readiness to determine whether a game "
        "is ready for price review or still awaiting lineups or data."
    )

    if not analyses:
        st.info("No games available.")
        return

    actions = sorted(
        {
            row["premarket_status"]
            for row in analyses
        }
    )

    selected = st.multiselect(
        "Show premarket statuses",
        actions,
        default=actions,
    )

    filtered = [
        row
        for row in analyses
        if row["premarket_status"] in selected
    ]

    st.dataframe(
        slate_frame(filtered),
        use_container_width=True,
        hide_index=True,
    )

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


def render_game_card(
    analyses: list[dict[str, Any]],
    selected_date: str,
) -> None:
    st.header("Game Card")

    if not analyses:
        st.info("No games available.")
        return

    labels = {
        row["matchup"]: row
        for row in analyses
    }

    item = labels[
        st.selectbox(
            "Select matchup",
            list(labels),
            key="game_card_matchup",
        )
    ]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Separation score",
        show_value(item["separation_score"], 1),
    )
    c2.metric("Readiness", item["readiness"])
    c3.metric(
        "Baseball-side advantage",
        item["baseball_advantage"],
    )
    c4.metric(
        "Confidence",
        f"{item['confidence']} · {item['completeness']}%",
    )

    details = item["details"]

    st.subheader("Starting pitching — season data")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Team": item["away"],
                    "Starter": item["away_starter"],
                    "Score": show_value(
                        item["away_sp_score"],
                        1,
                    ),
                    "ERA": show_value(
                        details.get("Away_ERA")
                    ),
                    "WHIP": show_value(
                        details.get("Away_WHIP")
                    ),
                    "K/9": show_value(
                        details.get("Away_K9")
                    ),
                    "BB/9": show_value(
                        details.get("Away_BB9")
                    ),
                },
                {
                    "Team": item["home"],
                    "Starter": item["home_starter"],
                    "Score": show_value(
                        item["home_sp_score"],
                        1,
                    ),
                    "ERA": show_value(
                        details.get("Home_ERA")
                    ),
                    "WHIP": show_value(
                        details.get("Home_WHIP")
                    ),
                    "K/9": show_value(
                        details.get("Home_K9")
                    ),
                    "BB/9": show_value(
                        details.get("Home_BB9")
                    ),
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
                    "Season baseline": show_value(
                        item["away_off_score"],
                        1,
                    ),
                    f"Vs {item['home_pitch_hand']}HP": show_value(
                        item["away_split_score"],
                        1,
                    ),
                    "Matchup score": show_value(
                        item["away_matchup_off_score"],
                        1,
                    ),
                    "Recent 14": show_value(
                        item["away_recent14_score"],
                        1,
                    ),
                    "Recent 30": show_value(
                        item["away_recent30_score"],
                        1,
                    ),
                    "Trend": item["away_recent_trend"],
                    "AVG": show_value(
                        details.get("Away_AVG"),
                        3,
                    ),
                    "OBP": show_value(
                        details.get("Away_OBP"),
                        3,
                    ),
                    "SLG": show_value(
                        details.get("Away_SLG"),
                        3,
                    ),
                    "OPS": show_value(
                        details.get("Away_OPS"),
                        3,
                    ),
                    "K%": show_value(
                        details.get("Away_K%"),
                        1,
                    ),
                    "BB%": show_value(
                        details.get("Away_BB%"),
                        1,
                    ),
                },
                {
                    "Team": item["home"],
                    "Season baseline": show_value(
                        item["home_off_score"],
                        1,
                    ),
                    f"Vs {item['away_pitch_hand']}HP": show_value(
                        item["home_split_score"],
                        1,
                    ),
                    "Matchup score": show_value(
                        item["home_matchup_off_score"],
                        1,
                    ),
                    "Recent 14": show_value(
                        item["home_recent14_score"],
                        1,
                    ),
                    "Recent 30": show_value(
                        item["home_recent30_score"],
                        1,
                    ),
                    "Trend": item["home_recent_trend"],
                    "AVG": show_value(
                        details.get("Home_AVG"),
                        3,
                    ),
                    "OBP": show_value(
                        details.get("Home_OBP"),
                        3,
                    ),
                    "SLG": show_value(
                        details.get("Home_SLG"),
                        3,
                    ),
                    "OPS": show_value(
                        details.get("Home_OPS"),
                        3,
                    ),
                    "K%": show_value(
                        details.get("Home_K%"),
                        1,
                    ),
                    "BB%": show_value(
                        details.get("Home_BB%"),
                        1,
                    ),
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
                    "Relief appearances": away_bp[
                        "team_appearances"
                    ],
                    "Multi-day arms": away_bp[
                        "multi_day_arms"
                    ],
                    "Max reliever pitches": away_bp[
                        "max_reliever_pitches"
                    ],
                },
                {
                    "Team": item["home"],
                    "Status": home_bp["status"],
                    "Games found": home_bp["games_found"],
                    "Relief pitches": home_bp["team_pitches"],
                    "Relief appearances": home_bp[
                        "team_appearances"
                    ],
                    "Multi-day arms": home_bp[
                        "multi_day_arms"
                    ],
                    "Max reliever pitches": home_bp[
                        "max_reliever_pitches"
                    ],
                },
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.info(
        f"Full-game context: {item['full_game_context']}"
    )

    with st.expander(
        f"{item['away']} reliever detail"
    ):
        st.dataframe(
            pd.DataFrame(away_bp["relievers"]),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander(
        f"{item['home']} reliever detail"
    ):
        st.dataframe(
            pd.DataFrame(home_bp["relievers"]),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Data completeness")
    availability = item["component_availability"]

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Component": "Probable starters",
                    "Status": (
                        "Available"
                        if (
                            item["away_starter"] != "TBD"
                            and item["home_starter"] != "TBD"
                        )
                        else "Pending"
                    ),
                },
                {
                    "Component": "Away starter season stats",
                    "Status": (
                        "Available"
                        if availability["away_starter"]
                        else "Missing"
                    ),
                },
                {
                    "Component": "Home starter season stats",
                    "Status": (
                        "Available"
                        if availability["home_starter"]
                        else "Missing"
                    ),
                },
                {
                    "Component": "Away season offense",
                    "Status": (
                        "Available"
                        if availability["away_offense"]
                        else "Missing"
                    ),
                },
                {
                    "Component": "Home season offense",
                    "Status": (
                        "Available"
                        if availability["home_offense"]
                        else "Missing"
                    ),
                },
                {
                    "Component": "Starter handedness",
                    "Status": (
                        f"{item['away_starter']}: "
                        f"{item['away_pitch_hand']} | "
                        f"{item['home_starter']}: "
                        f"{item['home_pitch_hand']}"
                    ),
                },
                {
                    "Component": "Offense handedness splits",
                    "Status": (
                        "Available"
                        if (
                            item["component_availability"][
                                "away_split"
                            ]
                            and item[
                                "component_availability"
                            ]["home_split"]
                        )
                        else "Partial / missing"
                    ),
                },
                {
                    "Component": "Confirmed lineups",
                    "Status": (
                        f"{item['lineup_status']} "
                        f"({item['away_lineup_count']}/"
                        f"{item['home_lineup_count']})"
                    ),
                },
                {
                    "Component": "Bullpen workload",
                    "Status": (
                        f"{item['away']}: "
                        f"{item['away_bullpen']['status']} | "
                        f"{item['home']}: "
                        f"{item['home_bullpen']['status']}"
                    ),
                },
                {
                    "Component": "Sportsbook odds",
                    "Status": "Manual submission below",
                },
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Market Workspace")
    st.caption(
        "The app compares the current sportsbook price with your preferred "
        "and maximum acceptable prices. It does not convert the matchup score "
        "into a win probability."
    )

    market = st.selectbox(
        "Market",
        [
            "Full-game ML",
            "F5 ML",
            "F5 -0.5",
            "Run line",
            "Total",
            "Player prop",
            "Live only",
        ],
        key=f"market-{item['game_pk']}",
    )

    sportsbook = st.selectbox(
        "Sportsbook",
        [
            "DraftKings",
            "FanDuel",
            "BetMGM",
            "Caesars",
            "Other",
        ],
        key=f"sportsbook-{item['game_pk']}",
    )

    with st.form(
        f"market-form-{item['game_pk']}"
    ):
        m1, m2 = st.columns(2)

        with m1:
            away_odds = st.number_input(
                f"{item['away']} odds",
                value=-110,
                step=1,
            )

        with m2:
            home_odds = st.number_input(
                f"{item['home']} odds",
                value=-110,
                step=1,
            )

        submitted = st.form_submit_button(
            "Analyze current market",
            type="primary",
        )

    state_key = f"market-state-{item['game_pk']}"

    if submitted:
        st.session_state[state_key] = {
            "away": int(away_odds),
            "home": int(home_odds),
        }

    odds_state = st.session_state.get(state_key)

    notes = st.text_area(
        "Context or thesis notes",
        placeholder=(
            "Lineup news, market movement, injury context, "
            "or reasons the price target was chosen."
        ),
        key=f"notes-{item['game_pk']}",
    )

    if not odds_state:
        st.warning(
            "Submit a two-sided market before evaluating a price decision."
        )
    else:
        away_odds = int(odds_state["away"])
        home_odds = int(odds_state["home"])

        try:
            away_nv, home_nv, hold = (
                no_vig_probabilities(
                    away_odds,
                    home_odds,
                )
            )
        except ValueError as exc:
            st.error(str(exc))
            return

        v1, v2, v3, v4 = st.columns(4)
        v1.metric(
            f"{item['away']} no-vig",
            f"{away_nv:.1%}",
        )
        v2.metric(
            f"{item['home']} no-vig",
            f"{home_nv:.1%}",
        )
        v3.metric(
            "Sportsbook hold",
            f"{hold:.1%}",
        )
        v4.metric(
            "Research lean",
            item["baseball_advantage"],
        )

        st.caption(
            "No-vig probability describes the current market consensus "
            "after removing hold; it is not the model's fair probability."
        )

        selection = st.selectbox(
            "Side being evaluated",
            [item["away"], item["home"]],
            index=(
                0
                if item["baseball_advantage"] == item["away"]
                else 1
            ),
            key=(
                f"decision-selection-"
                f"{item['game_pk']}"
            ),
        )

        selected_odds = (
            away_odds
            if selection == item["away"]
            else home_odds
        )

        opposing_odds = (
            home_odds
            if selection == item["away"]
            else away_odds
        )

        selected_no_vig = (
            away_nv
            if selection == item["away"]
            else home_nv
        )

        p1, p2 = st.columns(2)

        with p1:
            target_odds = st.number_input(
                "Preferred target price",
                value=int(selected_odds),
                step=1,
                key=(
                    f"target-{item['game_pk']}-"
                    f"{selection}"
                ),
                help=(
                    "The price you would prefer to receive. "
                    "Example: -135."
                ),
            )

        with p2:
            maximum_odds = st.number_input(
                "Maximum acceptable price",
                value=int(selected_odds - 5),
                step=1,
                key=(
                    f"maximum-{item['game_pk']}-"
                    f"{selection}"
                ),
                help=(
                    "The worst price you would still consider. "
                    "Example: -140."
                ),
            )

        final_action = st.selectbox(
            "Final action",
            [
                "UNDECIDED",
                "WAIT",
                "PASS",
                "BET PLACED",
            ],
            key=(
                f"final-action-"
                f"{item['game_pk']}"
            ),
        )

        try:
            decision = classify_decision(
                selection=selection,
                research_lean=item[
                    "baseball_advantage"
                ],
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
            d1.metric(
                "Recommendation",
                decision.recommendation,
            )
            d2.metric(
                "Price status",
                decision.price_status,
            )
            d3.metric(
                "Lifecycle",
                decision.lifecycle_status,
            )

            st.info(decision.rationale)

            snapshot_id = st.session_state.get(
                f"latest-snapshot-"
                f"{item['game_pk']}"
            )

            a1, a2 = st.columns(2)

            with a1:
                if st.button(
                    "Save market snapshot",
                    key=(
                        f"save-snapshot-"
                        f"{item['game_pk']}"
                    ),
                ):
                    try:
                        snapshot_id = (
                            save_market_snapshot(
                                item=item,
                                game_date=selected_date,
                                market_type=market,
                                selection=selection,
                                selection_odds=int(
                                    selected_odds
                                ),
                                opposing_odds=int(
                                    opposing_odds
                                ),
                                no_vig_probability=float(
                                    selected_no_vig
                                ),
                                market_status=(
                                    decision.recommendation
                                ),
                                notes=notes,
                                sportsbook=sportsbook,
                            )
                        )

                        st.session_state[
                            f"latest-snapshot-"
                            f"{item['game_pk']}"
                        ] = snapshot_id

                        st.session_state[
                            "latest_snapshot_id"
                        ] = snapshot_id

                        st.success(
                            "Market snapshot saved to Supabase."
                        )
                    except Exception as exc:
                        st.error(
                            f"Could not save snapshot: {exc}"
                        )

            with a2:
                if st.button(
                    "Save decision evaluation",
                    type="primary",
                    key=(
                        f"save-decision-"
                        f"{item['game_pk']}"
                    ),
                ):
                    try:
                        decision_id = (
                            save_research_decision(
                                snapshot_id=snapshot_id,
                                item=item,
                                game_date=selected_date,
                                sportsbook=sportsbook,
                                market_type=market,
                                selection=selection,
                                current_odds=int(
                                    selected_odds
                                ),
                                opposing_odds=int(
                                    opposing_odds
                                ),
                                no_vig_probability=float(
                                    selected_no_vig
                                ),
                                market_hold=float(hold),
                                target_odds=int(
                                    target_odds
                                ),
                                maximum_odds=int(
                                    maximum_odds
                                ),
                                recommendation=(
                                    decision.recommendation
                                ),
                                lifecycle_status=(
                                    decision.lifecycle_status
                                ),
                                price_status=(
                                    decision.price_status
                                ),
                                final_action=final_action,
                                rationale=(
                                    decision.rationale
                                ),
                                notes=notes,
                            )
                        )

                        st.success(
                            "Decision evaluation saved. "
                            f"ID: {decision_id}"
                        )
                    except Exception as exc:
                        st.error(
                            f"Could not save decision: {exc}"
                        )

            packet = build_strategy_packet(
                item,
                market,
                away_odds,
                home_odds,
                notes,
                decision.recommendation,
            )

            packet += (
                "\n\nMARKET WORKSPACE\n"
                f"Sportsbook: {sportsbook}\n"
                f"Evaluated selection: "
                f"{selection} {selected_odds:+d}\n"
                f"No-vig market probability: "
                f"{selected_no_vig:.1%}\n"
                f"Target price: "
                f"{int(target_odds):+d}\n"
                f"Maximum acceptable: "
                f"{int(maximum_odds):+d}\n"
                f"Recommendation: "
                f"{decision.recommendation}\n"
                f"Final action: {final_action}\n"
                f"Rationale: {decision.rationale}"
            )

            st.text_area(
                "Copy into the Betting Strategy thread",
                value=packet,
                height=500,
            )

            st.download_button(
                "Download strategy packet",
                packet.encode("utf-8"),
                (
                    f"strategy_packet_"
                    f"{item['game_pk']}.txt"
                ),
                "text/plain",
            )

    if item["errors"]:
        with st.expander(
            "Data retrieval warnings"
        ):
            for error in item["errors"]:
                st.write(f"- {error}")


def render_live_feed_tables(
    feed: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pitchers = pitcher_lines(feed)
    pitches = pitch_events(feed)
    batted_balls = batted_ball_events(feed)

    st.subheader("Pitching line")
    st.dataframe(
        pitchers,
        use_container_width=True,
        hide_index=True,
    )

    left, right = st.columns(2)

    with left:
        st.subheader("Command and velocity")
        st.dataframe(
            command_summary(pitches),
            use_container_width=True,
            hide_index=True,
        )

    with right:
        st.subheader("Contact allowed")
        st.dataframe(
            contact_summary(batted_balls),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("Batted-ball events"):
        st.dataframe(
            batted_balls,
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("Pitch-by-pitch events"):
        st.dataframe(
            pitches,
            use_container_width=True,
            hide_index=True,
        )

    return pitchers, pitches, batted_balls


def render_live_thesis_workspace(
    *,
    game_pk: int,
    game_date: str,
    away_team: str,
    home_team: str,
    away_score: int,
    home_score: int,
    inning: int,
    inning_half: str,
    outs: int,
    game_status: str,
    feed: dict[str, Any],
) -> None:
    st.divider()
    st.header("Live Thesis Engine")
    st.caption(
        "This engine evaluates whether the saved pregame thesis remains "
        "healthy. It does not create a new handicap or estimate win probability."
    )

    research_decision = get_latest_research_decision(
        game_pk
    )

    if not research_decision:
        st.warning(
            "No saved pregame research decision exists for this game. "
            "Save a decision evaluation from the Game Card before using "
            "the Live Thesis Engine."
        )
        return

    selected_team = decision_team(
        research_decision,
        away_team,
        home_team,
    )

    if selected_team is None:
        st.error(
            "The saved decision selection does not match either team in "
            "the current MLB live feed."
        )
        st.write(
            {
                "Saved selection": research_decision.get(
                    "selection"
                ),
                "Away team": away_team,
                "Home team": home_team,
            }
        )
        return

    try:
        auto_inputs = extract_live_thesis_inputs(
            feed,
            selected_team,
        )
        automatic_feed_available = True
    except Exception as exc:
        automatic_feed_available = False
        auto_inputs = {
            "away_score": away_score,
            "home_score": home_score,
            "favored_score": (
                home_score
                if selected_team == home_team
                else away_score
            ),
            "opponent_score": (
                away_score
                if selected_team == home_team
                else home_score
            ),
            "inning": inning,
            "inning_half": inning_half,
            "outs": outs,
            "runner_on_first": False,
            "runner_on_second": False,
            "runner_on_third": False,
            "tracked_pitcher_id": None,
            "tracked_pitcher_name": "",
            "pitch_count": 0,
            "strikes": 0,
            "first_pitch_strike_rate": None,
            "pitcher_walks": 0,
            "pitcher_strikeouts": 0,
            "batters_faced": 0,
            "pitcher_hard_hits_allowed": 0,
            "pitcher_barrels_allowed": 0,
            "balls_in_play_against_pitcher": 0,
            "favored_plate_appearances": 0,
            "favored_hard_hits": 0,
            "favored_barrels": 0,
            "favored_walks": 0,
            "favored_strikeouts": 0,
            "favored_pitches_seen": 0,
            "favored_starter_still_active": True,
        }
        st.warning(
            "Automatic MLB field mapping was unavailable. "
            f"Manual inputs remain active: {exc}"
        )

    st.session_state.setdefault(
        f"live-manual-stat-lock-{game_pk}",
        False,
    )
    auto_fields_updated = False
    if automatic_feed_available:
        auto_fields_updated = sync_live_widget_state(
            game_pk,
            auto_inputs,
        )

    away_score = safe_int(
        auto_inputs.get("away_score"),
        away_score,
    )
    home_score = safe_int(
        auto_inputs.get("home_score"),
        home_score,
    )
    inning = safe_int(
        auto_inputs.get("inning"),
        inning,
    )
    inning_half = str(
        auto_inputs.get("inning_half")
        or inning_half
        or ""
    )
    outs = safe_int(
        auto_inputs.get("outs"),
        outs,
    )
    game_status = str(
        auto_inputs.get("game_status")
        or game_status
        or ""
    )

    opponent_team = (
        home_team
        if selected_team == away_team
        else away_team
    )

    favored_team_is_home = (
        selected_team == home_team
    )

    favored_score = (
        home_score
        if favored_team_is_home
        else away_score
    )

    opponent_score = (
        away_score
        if favored_team_is_home
        else home_score
    )

    metadata = research_decision.get(
        "metadata"
    ) or {}

    st.subheader("Saved pregame thesis")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric(
        "Evaluated team",
        selected_team,
    )
    p2.metric(
        "Pregame recommendation",
        research_decision.get(
            "recommendation"
        ) or "N/A",
    )
    p3.metric(
        "Target price",
        display_signed_odds(
            research_decision.get(
                "target_odds"
            )
        ),
    )
    p4.metric(
        "Maximum price",
        display_signed_odds(
            research_decision.get(
                "maximum_odds"
            )
        ),
    )

    st.caption(
        f"Market: "
        f"{research_decision.get('market_type') or 'N/A'} · "
        f"Sportsbook: "
        f"{research_decision.get('sportsbook') or 'N/A'} · "
        f"Saved: "
        f"{research_decision.get('evaluated_at') or 'N/A'}"
    )

    rationale = (
        research_decision.get("rationale")
        or research_decision.get("notes")
    )

    if rationale:
        st.info(str(rationale))

    previous_snapshot = (
        get_latest_live_thesis_snapshot(
            game_pk
        )
    )

    if previous_snapshot:
        st.subheader("Most recent live evaluation")

        previous_columns = st.columns(4)
        previous_columns[0].metric(
            "Thesis",
            previous_snapshot.get(
                "thesis_status"
            ) or "N/A",
        )
        previous_columns[1].metric(
            "Decision",
            previous_snapshot.get(
                "decision"
            ) or "N/A",
        )
        previous_columns[2].metric(
            "Score",
            show_value(
                previous_snapshot.get(
                    "thesis_score"
                ),
                1,
            ),
        )
        previous_columns[3].metric(
            "Captured",
            previous_snapshot.get(
                "captured_at"
            ) or "N/A",
        )

    st.subheader("Current live inputs")
    st.caption(
        "MLB game state, starter command, contact, and offensive-process "
        "fields are prefilled from the live feed. Live odds, feed integrity, "
        "and bullpen context remain manual. Every populated value can be overridden."
    )

    if automatic_feed_available:
        update_message = (
            "Automatic MLB fields updated from the latest feed."
            if auto_fields_updated
            else "Automatic MLB field mapping is active."
        )
        st.success(update_message)

        control_col1, control_col2 = st.columns(2)
        with control_col1:
            st.checkbox(
                "Keep manual statistical overrides",
                key=f"live-manual-stat-lock-{game_pk}",
                help=(
                    "When enabled, automatic refreshes will not overwrite "
                    "pitching, contact, or offense fields. Live odds are "
                    "always preserved separately."
                ),
            )
        with control_col2:
            st.caption(
                "Last meaningful data change: "
                + str(
                    st.session_state.get(
                        f"live-last-data-change-{game_pk}",
                        "N/A",
                    )
                )
            )

        with st.expander("Review automatic MLB inputs"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Field": key,
                            "MLB feed value": value,
                        }
                        for key, value in auto_inputs.items()
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

    feed_status = st.selectbox(
        "Feed integrity",
        [
            FEED_CURRENT,
            FEED_STALE,
            FEED_CONFLICT,
        ],
        index=0,
        key=f"live-feed-status-{game_pk}",
    )

    live_price_col1, live_price_col2 = (
        st.columns(2)
    )

    with live_price_col1:
        current_live_odds = st.number_input(
            f"Current live odds — {selected_team}",
            value=safe_int(
                research_decision.get(
                    "current_odds"
                ),
                -110,
            ),
            step=1,
            key=f"live-current-odds-{game_pk}",
        )

    with live_price_col2:
        opposing_live_odds = st.number_input(
            f"Current live odds — {opponent_team}",
            value=safe_int(
                research_decision.get(
                    "opposing_odds"
                ),
                -110,
            ),
            step=1,
            key=f"live-opposing-odds-{game_pk}",
        )

    st.markdown("#### Favored starter command")

    command_col1, command_col2, command_col3 = (
        st.columns(3)
    )

    with command_col1:
        current_pitcher_name = st.text_input(
            f"Current / tracked pitcher for {selected_team}",
            value=str(
                auto_inputs.get("tracked_pitcher_name")
                or ""
            ),
            key=f"live-pitcher-name-{game_pk}",
        )

        current_pitcher_id = st.number_input(
            "Pitcher MLB ID, optional",
            min_value=0,
            value=safe_int(
                auto_inputs.get("tracked_pitcher_id")
            ),
            step=1,
            key=f"live-pitcher-id-{game_pk}",
        )

        pitch_count = st.number_input(
            "Pitch count",
            min_value=0,
            value=safe_int(
                auto_inputs.get("pitch_count")
            ),
            step=1,
            key=f"live-pitch-count-{game_pk}",
        )

    with command_col2:
        strikes = st.number_input(
            "Total strikes",
            min_value=0,
            value=safe_int(
                auto_inputs.get("strikes")
            ),
            step=1,
            key=f"live-strikes-{game_pk}",
        )

        pitcher_walks = st.number_input(
            "Walks issued",
            min_value=0,
            value=safe_int(
                auto_inputs.get("pitcher_walks")
            ),
            step=1,
            key=f"live-pitcher-walks-{game_pk}",
        )

        batters_faced = st.number_input(
            "Batters faced",
            min_value=0,
            value=safe_int(
                auto_inputs.get("batters_faced")
            ),
            step=1,
            key=f"live-batters-faced-{game_pk}",
        )

    with command_col3:
        first_pitch_strike_percentage = (
            st.number_input(
                "First-pitch strike %",
                min_value=0.0,
                max_value=100.0,
                value=round(
                    safe_float(
                        auto_inputs.get(
                            "first_pitch_strike_rate"
                        )
                    )
                    * 100,
                    1,
                ),
                step=1.0,
                key=(
                    f"live-first-pitch-strike-"
                    f"{game_pk}"
                ),
            )
        )

        pitcher_strikeouts = st.number_input(
            "Pitcher strikeouts",
            min_value=0,
            value=safe_int(
                auto_inputs.get("pitcher_strikeouts")
            ),
            step=1,
            key=f"live-pitcher-strikeouts-{game_pk}",
        )

        favored_starter_still_active = (
            st.checkbox(
                f"{selected_team} starter is still active",
                value=bool(
                    auto_inputs.get(
                        "favored_starter_still_active",
                        True,
                    )
                ),
                key=(
                    f"live-starter-active-"
                    f"{game_pk}"
                ),
            )
        )

    strike_rate = (
        float(strikes) / float(pitch_count)
        if pitch_count > 0
        else None
    )

    first_pitch_strike_rate = (
        float(first_pitch_strike_percentage)
        / 100.0
    )

    if strike_rate is not None:
        st.caption(
            f"Calculated strike rate: "
            f"{strike_rate:.1%}"
        )

    st.markdown(
        "#### Contact allowed by the favored starter"
    )

    contact_col1, contact_col2, contact_col3 = (
        st.columns(3)
    )

    with contact_col1:
        pitcher_hard_hits_allowed = (
            st.number_input(
                "Hard-hit balls allowed",
                min_value=0,
                value=safe_int(
                    auto_inputs.get(
                        "pitcher_hard_hits_allowed"
                    )
                ),
                step=1,
                key=(
                    f"live-hard-hits-allowed-"
                    f"{game_pk}"
                ),
            )
        )

    with contact_col2:
        pitcher_barrels_allowed = (
            st.number_input(
                "Barrels allowed",
                min_value=0,
                value=safe_int(
                    auto_inputs.get(
                        "pitcher_barrels_allowed"
                    )
                ),
                step=1,
                key=(
                    f"live-barrels-allowed-"
                    f"{game_pk}"
                ),
            )
        )

    with contact_col3:
        balls_in_play_against_pitcher = (
            st.number_input(
                "Balls in play against pitcher",
                min_value=0,
                value=safe_int(
                    auto_inputs.get(
                        "balls_in_play_against_pitcher"
                    )
                ),
                step=1,
                key=(
                    f"live-bip-against-"
                    f"{game_pk}"
                ),
            )
        )

    st.markdown(
        f"#### {selected_team} offensive process"
    )

    offense_col1, offense_col2, offense_col3 = (
        st.columns(3)
    )

    with offense_col1:
        favored_plate_appearances = (
            st.number_input(
                "Plate appearances",
                min_value=0,
                value=safe_int(
                    auto_inputs.get(
                        "favored_plate_appearances"
                    )
                ),
                step=1,
                key=(
                    f"live-offense-pa-"
                    f"{game_pk}"
                ),
            )
        )

        favored_hard_hits = st.number_input(
            "Hard-hit balls",
            min_value=0,
            value=safe_int(
                auto_inputs.get("favored_hard_hits")
            ),
            step=1,
            key=(
                f"live-offense-hard-hits-"
                f"{game_pk}"
            ),
        )

    with offense_col2:
        favored_barrels = st.number_input(
            "Barrels",
            min_value=0,
            value=safe_int(
                auto_inputs.get("favored_barrels")
            ),
            step=1,
            key=(
                f"live-offense-barrels-"
                f"{game_pk}"
            ),
        )

        favored_walks = st.number_input(
            "Walks",
            min_value=0,
            value=safe_int(
                auto_inputs.get("favored_walks")
            ),
            step=1,
            key=(
                f"live-offense-walks-"
                f"{game_pk}"
            ),
        )

    with offense_col3:
        favored_strikeouts = (
            st.number_input(
                "Strikeouts",
                min_value=0,
                value=safe_int(
                    auto_inputs.get(
                        "favored_strikeouts"
                    )
                ),
                step=1,
                key=(
                    f"live-offense-strikeouts-"
                    f"{game_pk}"
                ),
            )
        )

        favored_pitches_seen = (
            st.number_input(
                "Pitches seen",
                min_value=0,
                value=safe_int(
                    auto_inputs.get(
                        "favored_pitches_seen"
                    )
                ),
                step=1,
                key=(
                    f"live-offense-pitches-seen-"
                    f"{game_pk}"
                ),
            )
        )

    st.markdown("#### Bullpen outlook")

    bullpen_options = [
        "UNKNOWN",
        "FULLY AVAILABLE",
        "MOSTLY AVAILABLE",
        "LIMITED",
        "COMPROMISED",
    ]

    bullpen_col1, bullpen_col2 = (
        st.columns(2)
    )

    with bullpen_col1:
        favored_bullpen_status = (
            st.selectbox(
                f"{selected_team} bullpen",
                bullpen_options,
                index=bullpen_default_index(
                    metadata.get(
                        "favored_bullpen_status"
                    )
                ),
                key=(
                    f"live-favored-bullpen-"
                    f"{game_pk}"
                ),
            )
        )

        favored_key_reliever_unavailable = (
            st.checkbox(
                f"Key {selected_team} reliever unavailable",
                value=False,
                key=(
                    f"live-key-reliever-out-"
                    f"{game_pk}"
                ),
            )
        )

    with bullpen_col2:
        opponent_bullpen_status = (
            st.selectbox(
                f"{opponent_team} bullpen",
                bullpen_options,
                index=bullpen_default_index(
                    metadata.get(
                        "opponent_bullpen_status"
                    )
                ),
                key=(
                    f"live-opponent-bullpen-"
                    f"{game_pk}"
                ),
            )
        )

        opponent_starter_removed = (
            st.checkbox(
                f"{opponent_team} starter has been removed",
                value=False,
                key=(
                    f"live-opponent-starter-removed-"
                    f"{game_pk}"
                ),
            )
        )

    evaluate_clicked = st.button(
        "Evaluate live thesis",
        type="primary",
        key=f"evaluate-live-thesis-{game_pk}",
    )

    result_key = (
        f"live-thesis-result-{game_pk}"
    )

    if evaluate_clicked:
        try:
            result = evaluate_live_thesis(
                feed_status=feed_status,
                target_odds=safe_int(
                    research_decision.get(
                        "target_odds"
                    )
                ),
                maximum_odds=safe_int(
                    research_decision.get(
                        "maximum_odds"
                    )
                ),
                current_live_odds=int(
                    current_live_odds
                ),
                pitch_count=int(pitch_count),
                strikes=int(strikes),
                first_pitch_strike_rate=float(
                    first_pitch_strike_rate
                ),
                pitcher_walks=int(
                    pitcher_walks
                ),
                batters_faced=int(
                    batters_faced
                ),
                pitcher_hard_hits_allowed=int(
                    pitcher_hard_hits_allowed
                ),
                pitcher_barrels_allowed=int(
                    pitcher_barrels_allowed
                ),
                balls_in_play_against_pitcher=int(
                    balls_in_play_against_pitcher
                ),
                favored_plate_appearances=int(
                    favored_plate_appearances
                ),
                favored_hard_hits=int(
                    favored_hard_hits
                ),
                favored_barrels=int(
                    favored_barrels
                ),
                favored_walks=int(
                    favored_walks
                ),
                favored_strikeouts=int(
                    favored_strikeouts
                ),
                favored_pitches_seen=int(
                    favored_pitches_seen
                ),
                favored_starter_still_active=bool(
                    favored_starter_still_active
                ),
                inning=int(inning),
                favored_bullpen_status=(
                    favored_bullpen_status
                ),
                opponent_bullpen_status=(
                    opponent_bullpen_status
                ),
                favored_key_reliever_unavailable=bool(
                    favored_key_reliever_unavailable
                ),
                opponent_starter_removed=bool(
                    opponent_starter_removed
                ),
                favored_team_is_home=bool(
                    favored_team_is_home
                ),
                favored_score=int(
                    favored_score
                ),
                opponent_score=int(
                    opponent_score
                ),
            )

            st.session_state[result_key] = {
                "result": result,
                "inputs": {
                    "feed_status": feed_status,
                    "current_live_odds": int(
                        current_live_odds
                    ),
                    "opposing_live_odds": int(
                        opposing_live_odds
                    ),
                    "current_pitcher_name": (
                        current_pitcher_name.strip()
                    ),
                    "current_pitcher_id": int(
                        current_pitcher_id
                    ),
                    "pitch_count": int(
                        pitch_count
                    ),
                    "strikes": int(strikes),
                    "strike_rate": (
                        strike_rate
                    ),
                    "first_pitch_strike_rate": float(
                        first_pitch_strike_rate
                    ),
                    "pitcher_walks": int(
                        pitcher_walks
                    ),
                    "pitcher_strikeouts": int(
                        pitcher_strikeouts
                    ),
                    "batters_faced": int(
                        batters_faced
                    ),
                    "pitcher_hard_hits_allowed": int(
                        pitcher_hard_hits_allowed
                    ),
                    "pitcher_barrels_allowed": int(
                        pitcher_barrels_allowed
                    ),
                    "balls_in_play_against_pitcher": int(
                        balls_in_play_against_pitcher
                    ),
                    "favored_plate_appearances": int(
                        favored_plate_appearances
                    ),
                    "favored_hard_hits": int(
                        favored_hard_hits
                    ),
                    "favored_barrels": int(
                        favored_barrels
                    ),
                    "favored_walks": int(
                        favored_walks
                    ),
                    "favored_strikeouts": int(
                        favored_strikeouts
                    ),
                    "favored_pitches_seen": int(
                        favored_pitches_seen
                    ),
                    "favored_starter_still_active": bool(
                        favored_starter_still_active
                    ),
                    "favored_bullpen_status": (
                        favored_bullpen_status
                    ),
                    "opponent_bullpen_status": (
                        opponent_bullpen_status
                    ),
                    "favored_key_reliever_unavailable": bool(
                        favored_key_reliever_unavailable
                    ),
                    "opponent_starter_removed": bool(
                        opponent_starter_removed
                    ),
                },
            }

        except Exception as exc:
            st.error(
                f"Could not evaluate live thesis: {exc}"
            )

    saved_state = st.session_state.get(
        result_key
    )

    if not saved_state:
        return

    result = saved_state["result"]
    saved_inputs = saved_state["inputs"]

    st.subheader("Live thesis result")

    result_columns = st.columns(4)
    result_columns[0].metric(
        "Thesis status",
        result["thesis_status"],
    )
    result_columns[1].metric(
        "Decision",
        result["decision"],
    )
    result_columns[2].metric(
        "Thesis score",
        show_value(
            result["thesis_score"],
            1,
        ),
    )
    result_columns[3].metric(
        "Price status",
        result["price_status"],
    )

    validation_status = result.get("input_validation_status")
    effective_feed_status = result.get("effective_feed_status")
    missing_fields = result.get("missing_fields") or []
    validation_issues = result.get("validation_issues") or []

    if validation_status or effective_feed_status:
        st.caption(
            f"Input validation: {validation_status or 'N/A'} · "
            f"Effective feed status: {effective_feed_status or saved_inputs['feed_status']}"
        )

    if missing_fields:
        st.warning(
            "Missing live fields: " + ", ".join(map(str, missing_fields))
        )

    if validation_issues:
        st.error(
            "Live-data conflicts: " + "; ".join(map(str, validation_issues))
        )

    component_frame = pd.DataFrame(
        [
            {
                "Component": "Starter command",
                "Status": result[
                    "starter_command_status"
                ],
                "Score": result[
                    "score_components"
                ].get("starter_command"),
            },
            {
                "Component": "Contact quality",
                "Status": result[
                    "contact_quality_status"
                ],
                "Score": result[
                    "score_components"
                ].get("contact_quality"),
            },
            {
                "Component": "Offensive process",
                "Status": result[
                    "offense_status"
                ],
                "Score": result[
                    "score_components"
                ].get("offensive_process"),
            },
            {
                "Component": "Bullpen outlook",
                "Status": result[
                    "bullpen_status"
                ],
                "Score": result[
                    "score_components"
                ].get("bullpen_outlook"),
            },
            {
                "Component": "Game state",
                "Status": result[
                    "score_components"
                ].get("game_state_status"),
                "Score": result[
                    "score_components"
                ].get("game_state"),
            },
            {
                "Component": "Feed confidence",
                "Status": saved_inputs[
                    "feed_status"
                ],
                "Score": result[
                    "score_components"
                ].get("feed_confidence"),
            },
        ]
    )

    st.dataframe(
        component_frame,
        use_container_width=True,
        hide_index=True,
    )

    if result["trigger_reason"]:
        st.success(
            result["trigger_reason"]
        )

    if result["warning_reason"]:
        st.warning(
            result["warning_reason"]
        )

    if result["active_thesis_killers"]:
        st.error(
            "Active thesis killers: "
            + "; ".join(
                result[
                    "active_thesis_killers"
                ]
            )
        )

    if st.button(
        "Save live thesis snapshot",
        type="primary",
        key=f"save-live-snapshot-{game_pk}",
    ):
        snapshot_payload = {
            "research_decision_id": (
                research_decision.get(
                    "decision_id"
                )
            ),
            "game_pk": int(game_pk),
            "game_date": game_date,
            "away_team": away_team,
            "home_team": home_team,
            "inning": int(inning),
            "inning_half": inning_half or None,
            "outs": int(outs),
            "away_score": int(away_score),
            "home_score": int(home_score),
            "runner_on_first": False,
            "runner_on_second": False,
            "runner_on_third": False,
            "current_pitcher_id": (
                saved_inputs[
                    "current_pitcher_id"
                ]
                if saved_inputs[
                    "current_pitcher_id"
                ] > 0
                else None
            ),
            "current_pitcher_name": (
                saved_inputs[
                    "current_pitcher_name"
                ]
                or None
            ),
            "pitcher_team": selected_team,
            "pitch_count": saved_inputs[
                "pitch_count"
            ],
            "strikes": saved_inputs[
                "strikes"
            ],
            "strike_rate": saved_inputs[
                "strike_rate"
            ],
            "first_pitch_strike_rate": (
                saved_inputs[
                    "first_pitch_strike_rate"
                ]
            ),
            "walks": saved_inputs[
                "pitcher_walks"
            ],
            "strikeouts": saved_inputs[
                "pitcher_strikeouts"
            ],
            "hard_hits": saved_inputs[
                "pitcher_hard_hits_allowed"
            ],
            "barrels": saved_inputs[
                "pitcher_barrels_allowed"
            ],
            "starter_command_status": result[
                "starter_command_status"
            ],
            "contact_quality_status": result[
                "contact_quality_status"
            ],
            "offense_status": result[
                "offense_status"
            ],
            "bullpen_status": result[
                "bullpen_status"
            ],
            "thesis_status": result[
                "thesis_status"
            ],
            "thesis_score": result[
                "thesis_score"
            ],
            "live_market_type": (
                research_decision.get(
                    "market_type"
                )
            ),
            "live_selection": selected_team,
            "live_odds": saved_inputs[
                "current_live_odds"
            ],
            "opposing_live_odds": (
                saved_inputs[
                    "opposing_live_odds"
                ]
            ),
            "price_status": result[
                "price_status"
            ],
            "decision": result[
                "decision"
            ],
            "trigger_reason": result[
                "trigger_reason"
            ],
            "warning_reason": (
                result["warning_reason"]
                or None
            ),
            "active_thesis_killers": result[
                "active_thesis_killers"
            ],
            "feed_status": saved_inputs[
                "feed_status"
            ],
            "feed_timestamp": datetime.now(
            ).astimezone().isoformat(),
            "metadata": {
                "game_status": game_status,
                "input_source": (
                    "MLB_AUTO_WITH_MANUAL_OVERRIDES"
                    if automatic_feed_available
                    else "MANUAL_FALLBACK"
                ),
                "tracked_team": selected_team,
                "opponent_team": opponent_team,
                "target_odds": research_decision.get(
                    "target_odds"
                ),
                "maximum_odds": research_decision.get(
                    "maximum_odds"
                ),
                "batters_faced": saved_inputs[
                    "batters_faced"
                ],
                "balls_in_play_against_pitcher": (
                    saved_inputs[
                        "balls_in_play_against_pitcher"
                    ]
                ),
                "favored_plate_appearances": (
                    saved_inputs[
                        "favored_plate_appearances"
                    ]
                ),
                "favored_hard_hits": saved_inputs[
                    "favored_hard_hits"
                ],
                "favored_barrels": saved_inputs[
                    "favored_barrels"
                ],
                "favored_walks": saved_inputs[
                    "favored_walks"
                ],
                "favored_strikeouts": saved_inputs[
                    "favored_strikeouts"
                ],
                "favored_pitches_seen": saved_inputs[
                    "favored_pitches_seen"
                ],
                "favored_starter_still_active": (
                    saved_inputs[
                        "favored_starter_still_active"
                    ]
                ),
                "favored_bullpen_status": (
                    saved_inputs[
                        "favored_bullpen_status"
                    ]
                ),
                "opponent_bullpen_status": (
                    saved_inputs[
                        "opponent_bullpen_status"
                    ]
                ),
                "favored_key_reliever_unavailable": (
                    saved_inputs[
                        "favored_key_reliever_unavailable"
                    ]
                ),
                "opponent_starter_removed": (
                    saved_inputs[
                        "opponent_starter_removed"
                    ]
                ),
                "score_components": result[
                    "score_components"
                ],
            },
        }

        try:
            saved_snapshot = (
                save_live_thesis_snapshot(
                    snapshot_payload
                )
            )

            st.success(
                "Live thesis snapshot saved. "
                f"ID: "
                f"{saved_snapshot['live_snapshot_id']}"
            )

        except Exception as exc:
            st.error(
                "Could not save live thesis snapshot: "
                f"{exc}"
            )

    history = get_live_thesis_snapshots(
        game_pk,
        limit=100,
    )

    if history:
        st.subheader("Saved live thesis history")

        history_frame = pd.DataFrame(history)

        preferred_columns = [
            "captured_at",
            "inning",
            "inning_half",
            "away_score",
            "home_score",
            "live_selection",
            "live_odds",
            "thesis_status",
            "thesis_score",
            "price_status",
            "decision",
            "feed_status",
        ]

        available_columns = [
            column
            for column in preferred_columns
            if column in history_frame.columns
        ]

        st.dataframe(
            history_frame[available_columns],
            use_container_width=True,
            hide_index=True,
        )


def render_live(
    games: list[dict[str, Any]],
    selected_date: str,
) -> None:
    st.header("Live Desk")
    st.caption(
        "The v0.7.3 Live Refresh Controller polls only the selected MLB game. "
        "Display refreshes do not create database rows, and live odds remain manual."
    )

    if not games:
        st.info("No games found.")
        return

    labels = {
        game_label(game): game.get("gamePk")
        for game in games
    }

    choice = st.selectbox(
        "Select live game",
        list(labels),
        key="live_game",
    )
    game_pk = safe_int(labels[choice])

    refresh_col1, refresh_col2 = st.columns(2)
    with refresh_col1:
        auto_refresh = st.toggle(
            "Auto-refresh selected game",
            value=False,
            key=f"live-auto-refresh-{game_pk}",
            help=(
                "Refreshes only while this Live Desk is open. "
                "It does not run as a background service."
            ),
        )
    with refresh_col2:
        refresh_seconds = st.selectbox(
            "Refresh interval",
            [15, 30, 60],
            index=0,
            format_func=lambda value: f"{value} seconds",
            key=f"live-refresh-interval-{game_pk}",
            disabled=not auto_refresh,
        )

    run_every = f"{refresh_seconds}s" if auto_refresh else None

    @st.fragment(run_every=run_every)
    def render_selected_live_game() -> None:
        manual_col, status_col = st.columns([1, 2])
        with manual_col:
            if st.button(
                "Refresh live feed now",
                key=f"refresh-live-now-{game_pk}",
                use_container_width=True,
            ):
                get_live_feed.clear(game_pk)
                st.rerun()

        request_time = datetime.now().astimezone()

        try:
            feed = get_live_feed(game_pk)
        except Exception as exc:
            st.error(f"Could not retrieve live game feed: {exc}")
            return

        with status_col:
            mode = (
                f"Auto every {refresh_seconds}s"
                if auto_refresh
                else "Manual refresh"
            )
            st.caption(
                f"Mode: {mode} · Last app request: "
                f"{request_time.strftime('%-I:%M:%S %p %Z')} · "
                f"MLB source timestamp: {feed_source_timestamp(feed)}"
            )

        game_data = feed.get("gameData", {})
        live_data = feed.get("liveData", {})
        linescore = live_data.get("linescore", {})

        away = (
            game_data.get("teams", {})
            .get("away", {})
            .get("name", "Away")
        )
        home = (
            game_data.get("teams", {})
            .get("home", {})
            .get("name", "Home")
        )
        away_score = safe_int(
            linescore.get("teams", {})
            .get("away", {})
            .get("runs", 0)
        )
        home_score = safe_int(
            linescore.get("teams", {})
            .get("home", {})
            .get("runs", 0)
        )
        inning = safe_int(linescore.get("currentInning", 0))
        inning_half = str(linescore.get("inningState", "") or "")
        outs = safe_int(linescore.get("outs", 0))
        game_status = str(
            game_data.get("status", {}).get("detailedState", "") or ""
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(away, away_score)
        c2.metric(home, home_score)
        c3.metric("Game state", f"{inning_half} {inning}".strip())
        c4.metric("Status", game_status)

        render_live_feed_tables(feed)
        render_live_thesis_workspace(
            game_pk=game_pk,
            game_date=selected_date,
            away_team=away,
            home_team=home,
            away_score=away_score,
            home_score=home_score,
            inning=inning,
            inning_half=inning_half,
            outs=outs,
            game_status=game_status,
            feed=feed,
        )

    render_selected_live_game()


def render_journal() -> None:
    st.header("Persistent Journal")

    status, message = database_status()

    if status != "CONNECTED":
        st.error(
            "Supabase is not connected. Complete the setup "
            "instructions before saving journal data."
        )
        st.caption(message)
        return

    tabs = st.tabs(
        [
            "New bet",
            "Settle bet",
            "Review bet",
            "Stored bets",
            "Market snapshots",
            "Decision history",
            "Live thesis history",
        ]
    )

    with tabs[0]:
        c1, c2, c3 = st.columns(3)

        with c1:
            entry_date = st.date_input(
                "Date",
                value=date.today(),
                key="db_journal_date",
            )

            game_pk = st.number_input(
                "MLB game ID (optional)",
                min_value=0,
                value=0,
                step=1,
            )

            market = st.selectbox(
                "Market",
                [
                    "Full-game ML",
                    "F5 ML",
                    "F5 -0.5",
                    "Run line",
                    "Total",
                    "Player prop",
                ],
                key="db_market",
            )

        with c2:
            selection = st.text_input(
                "Selection",
                placeholder="Phillies F5 -0.5",
                key="db_selection",
            )

            odds = st.number_input(
                "Entry odds",
                value=-110,
                step=1,
                key="db_odds",
            )

            stake = st.number_input(
                "Stake",
                min_value=0.0,
                value=5.0,
                step=1.0,
                key="db_stake",
            )

        with c3:
            decision_status = st.selectbox(
                "Decision status",
                [
                    "VALUE CANDIDATE",
                    "PRICE SENSITIVE",
                    "LIVE WATCH",
                    "MANUAL BET",
                ],
                key="db_status",
            )

            snapshot_id = st.text_input(
                "Snapshot ID (optional)",
                value=st.session_state.get(
                    "latest_snapshot_id",
                    "",
                ),
                key="db_snapshot",
            )

        notes = st.text_area(
            "Thesis and entry context",
            key="db_notes",
        )

        if st.button(
            "Save bet to Supabase",
            type="primary",
        ):
            if not selection.strip():
                st.error("Selection is required.")
            else:
                try:
                    bet_id = save_bet(
                        snapshot_id=(
                            snapshot_id.strip()
                            or None
                        ),
                        game_pk=(
                            int(game_pk)
                            if game_pk
                            else None
                        ),
                        game_date=(
                            entry_date.isoformat()
                        ),
                        market_type=market,
                        selection=selection.strip(),
                        entry_odds=int(odds),
                        stake=float(stake),
                        decision_status=(
                            decision_status
                        ),
                        notes=notes,
                    )

                    st.success(
                        f"Bet saved. ID: {bet_id}"
                    )
                except Exception as exc:
                    st.error(
                        f"Could not save bet: {exc}"
                    )

    bets = load_bets()

    with tabs[1]:
        if bets.empty:
            st.info("No stored bets.")
        else:
            labels = {
                (
                    f"{row.get('placed_at', '')} | "
                    f"{row.get('selection', '')} | "
                    f"{row.get('entry_odds', '')} | "
                    f"{row.get('result', '')}"
                ): row["bet_id"]
                for _, row in bets.iterrows()
            }

            label = st.selectbox(
                "Choose bet",
                list(labels),
                key="settle_bet",
            )

            result = st.selectbox(
                "Result",
                [
                    "Open",
                    "Win",
                    "Loss",
                    "Push",
                    "Void",
                ],
                key="settle_result",
            )

            profit_loss = st.number_input(
                "Profit / loss",
                value=0.0,
                step=1.0,
                key="settle_pl",
            )

            closing_odds = st.number_input(
                "Closing odds",
                value=-110,
                step=1,
                key="settle_close",
            )

            if st.button(
                "Update bet result"
            ):
                try:
                    update_bet_result(
                        labels[label],
                        result,
                        float(profit_loss),
                        int(closing_odds),
                    )

                    st.success("Bet updated.")
                except Exception as exc:
                    st.error(
                        f"Could not update bet: {exc}"
                    )

    with tabs[2]:
        if bets.empty:
            st.info("No stored bets.")
        else:
            labels = {
                (
                    f"{row.get('game_date', '')} | "
                    f"{row.get('selection', '')} | "
                    f"{row.get('result', '')}"
                ): row["bet_id"]
                for _, row in bets.iterrows()
            }

            label = st.selectbox(
                "Choose bet to review",
                list(labels),
                key="review_bet",
            )

            thesis = st.text_area(
                "Original thesis",
                key="review_thesis",
            )

            thesis_killers = st.text_area(
                "Thesis killers / cancellation conditions",
                key="review_killers",
            )

            thesis_broken = st.checkbox(
                "Thesis broke during the game",
                key="review_broken",
            )

            c1, c2 = st.columns(2)

            with c1:
                execution_grade = st.selectbox(
                    "Execution grade",
                    ["A", "B", "C", "D", "F"],
                    key="exec_grade",
                )

            with c2:
                thesis_grade = st.selectbox(
                    "Thesis grade",
                    ["A", "B", "C", "D", "F"],
                    key="thesis_grade",
                )

            lesson = st.text_area(
                "Postgame lesson",
                key="review_lesson",
            )

            if st.button("Save review"):
                try:
                    save_bet_review(
                        labels[label],
                        thesis,
                        thesis_killers,
                        thesis_broken,
                        execution_grade,
                        thesis_grade,
                        lesson,
                    )

                    st.success("Review saved.")
                except Exception as exc:
                    st.error(
                        f"Could not save review: {exc}"
                    )

    with tabs[3]:
        bets = load_bets()

        if bets.empty:
            st.info("No stored bets.")
        else:
            st.dataframe(
                bets,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download bets CSV",
                bets.to_csv(
                    index=False
                ).encode("utf-8"),
                "mlb_bets_backup.csv",
                "text/csv",
            )

        reviews = load_reviews()

        if not reviews.empty:
            st.subheader("Stored reviews")
            st.dataframe(
                reviews,
                use_container_width=True,
                hide_index=True,
            )

    with tabs[4]:
        snapshots = load_snapshots()

        if snapshots.empty:
            st.info(
                "No market snapshots saved yet."
            )
        else:
            st.dataframe(
                snapshots,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download snapshots CSV",
                snapshots.to_csv(
                    index=False
                ).encode("utf-8"),
                "mlb_market_snapshots_backup.csv",
                "text/csv",
            )

    with tabs[5]:
        decisions = load_decisions()

        if decisions.empty:
            st.info(
                "No decision evaluations saved yet."
            )
        else:
            st.dataframe(
                decisions,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download decisions CSV",
                decisions.to_csv(
                    index=False
                ).encode("utf-8"),
                (
                    "mlb_research_decisions_"
                    "backup.csv"
                ),
                "text/csv",
            )

    with tabs[6]:
        live_snapshots = (
            load_live_thesis_snapshots()
        )

        if live_snapshots.empty:
            st.info(
                "No live thesis snapshots saved yet."
            )
        else:
            st.dataframe(
                live_snapshots,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download live thesis CSV",
                live_snapshots.to_csv(
                    index=False
                ).encode("utf-8"),
                (
                    "mlb_live_thesis_snapshots_"
                    "backup.csv"
                ),
                "text/csv",
            )


st.title("⚾ MLB Trading Desk v0.7.3")

with st.sidebar:
    selected_date = st.date_input(
        "Game date",
        value=date.today(),
    ).isoformat()

    page = st.radio(
        "Workspace",
        [
            "Dashboard",
            "Slate",
            "Game Card",
            "Live Desk",
            "Journal",
        ],
    )

    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = (
            datetime.now().strftime(
                "%-I:%M %p"
            )
        )

    if st.button("Refresh MLB data"):
        st.cache_data.clear()

        st.session_state.last_refresh = (
            datetime.now().strftime(
                "%-I:%M %p"
            )
        )

    db_state, db_message = (
        database_status()
    )

    if db_state == "CONNECTED":
        st.success("Database: Connected")

        try:
            register_model_version()
        except Exception as exc:
            st.warning(
                "Database connected, but v0.7 model "
                f"registration failed: {exc}"
            )

    elif db_state == "NOT CONFIGURED":
        st.warning(
            "Database: Not configured"
        )

    else:
        st.error(
            f"Database: {db_state}"
        )

    with st.expander(
        "Database details"
    ):
        st.write(db_message)


try:
    games = get_schedule(selected_date)
except Exception as exc:
    st.error(
        f"Could not reach MLB Stats API: {exc}"
    )
    games = []


analyses = (
    analyze_slate(
        games,
        CURRENT_SEASON,
        selected_date,
    )
    if (
        page
        in {
            "Dashboard",
            "Slate",
            "Game Card",
        }
        and games
    )
    else []
)


if page == "Dashboard":
    render_dashboard(
        analyses,
        selected_date,
        st.session_state.last_refresh,
    )

elif page == "Slate":
    render_slate(analyses)

elif page == "Game Card":
    render_game_card(
        analyses,
        selected_date,
    )

elif page == "Live Desk":
    render_live(
        games,
        selected_date,
    )

else:
    render_journal()
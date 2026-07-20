from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


THESIS_NOT_READY = "NOT READY"
THESIS_INTACT = "INTACT"
THESIS_STRENGTHENING = "STRENGTHENING"
THESIS_WEAKENING = "WEAKENING"
THESIS_INVALIDATED = "INVALIDATED"

DECISION_WATCH = "WATCH"
DECISION_ENTER_CONSIDERATION = "ENTER CONSIDERATION"
DECISION_PASS = "PASS"
DECISION_EXIT_THESIS = "EXIT THESIS"
DECISION_DATA_CHECK = "DATA CHECK"

FEED_CURRENT = "LIVE DATA CURRENT"
FEED_STALE = "LIVE DATA STALE"
FEED_CONFLICT = "LIVE DATA CONFLICT"

PRICE_WORSE_THAN_MAXIMUM = "WORSE THAN MAXIMUM"
PRICE_ACCEPTABLE = "ACCEPTABLE"
PRICE_TARGET_REACHED = "TARGET REACHED"
PRICE_SIGNIFICANT_DISCOUNT = "SIGNIFICANT DISCOUNT"
PRICE_SUSPICIOUS_DISCOUNT = "SUSPICIOUS DISCOUNT"
PRICE_NOT_AVAILABLE = "NOT AVAILABLE"


@dataclass
class LiveThesisResult:
    starter_command_status: str
    contact_quality_status: str
    offense_status: str
    bullpen_status: str

    thesis_score: float
    thesis_status: str

    price_status: str
    decision: str

    trigger_reason: str
    warning_reason: str

    active_thesis_killers: list[str]
    score_components: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def american_odds_to_decimal(odds: int) -> float:
    if odds == 0:
        raise ValueError("American odds cannot be zero.")

    if odds > 0:
        return 1 + (odds / 100)

    return 1 + (100 / abs(odds))


def american_odds_to_implied_probability(odds: int) -> float:
    if odds == 0:
        raise ValueError("American odds cannot be zero.")

    if odds > 0:
        return 100 / (odds + 100)

    return abs(odds) / (abs(odds) + 100)


def odds_are_better(current_odds: int, comparison_odds: int) -> bool:
    """
    Returns True when current_odds represent a better price for the bettor.

    Examples:
    -130 is better than -140.
    +120 is better than +105.
    +100 is better than -105.
    """
    current_probability = american_odds_to_implied_probability(current_odds)
    comparison_probability = american_odds_to_implied_probability(comparison_odds)

    return current_probability < comparison_probability


def odds_are_equal_or_better(
    current_odds: int,
    comparison_odds: int,
) -> bool:
    if current_odds == comparison_odds:
        return True

    return odds_are_better(current_odds, comparison_odds)


def price_improvement_points(
    current_odds: int,
    reference_odds: int,
) -> float:
    """
    Measures improvement using implied-probability percentage points.

    Positive values mean the current price is better for the bettor.
    """
    reference_probability = american_odds_to_implied_probability(
        reference_odds
    )
    current_probability = american_odds_to_implied_probability(
        current_odds
    )

    return (reference_probability - current_probability) * 100


def grade_starter_command(
    *,
    pitch_count: int | None,
    strikes: int | None,
    first_pitch_strike_rate: float | None,
    walks: int | None,
    batters_faced: int | None = None,
) -> tuple[str, float, list[str]]:
    pitch_count_value = _safe_int(pitch_count)
    strikes_value = _safe_int(strikes)
    walks_value = _safe_int(walks)
    batters_value = _safe_int(batters_faced)

    killers: list[str] = []

    if (
        pitch_count_value < 15
        and batters_value < 4
    ):
        return "NOT READY", 0.0, killers

    strike_rate = 0.0

    if pitch_count_value > 0:
        strike_rate = strikes_value / pitch_count_value

    first_pitch_rate = _safe_float(
        first_pitch_strike_rate,
        default=0.0,
    )

    if strike_rate < 0.56:
        killers.append("Starter strike rate below 56%.")

    if walks_value >= 3:
        killers.append("Starter issued at least three early walks.")

    if strike_rate >= 0.66 and first_pitch_rate >= 0.62:
        if walks_value <= 1:
            return "STRONG", 25.0, killers

    if strike_rate >= 0.61:
        if walks_value <= 1:
            return "ACCEPTABLE", 13.0, killers

    if strike_rate >= 0.56:
        if walks_value <= 2:
            return "WEAKENING", -12.0, killers

    return "FAILURE", -25.0, killers


def grade_contact_quality(
    *,
    hard_hits: int | None,
    barrels: int | None,
    balls_in_play: int | None = None,
) -> tuple[str, float, list[str]]:
    hard_hit_value = _safe_int(hard_hits)
    barrel_value = _safe_int(barrels)
    balls_in_play_value = _safe_int(balls_in_play)

    killers: list[str] = []

    if balls_in_play_value == 0 and hard_hit_value == 0:
        return "NOT READY", 0.0, killers

    if barrel_value >= 2:
        killers.append("Favored starter allowed multiple barrels.")

    if hard_hit_value >= 5:
        killers.append("Favored starter allowed repeated hard contact.")

    if barrel_value == 0 and hard_hit_value <= 1:
        return "STRONG", 25.0, killers

    if barrel_value <= 1 and hard_hit_value <= 3:
        return "ACCEPTABLE", 12.0, killers

    if barrel_value <= 1 and hard_hit_value <= 5:
        return "WEAKENING", -12.0, killers

    return "FAILURE", -25.0, killers


def grade_offensive_process(
    *,
    plate_appearances: int | None,
    hard_hits: int | None,
    barrels: int | None,
    walks: int | None,
    strikeouts: int | None,
    pitches_seen: int | None = None,
) -> tuple[str, float, list[str]]:
    plate_appearance_value = _safe_int(plate_appearances)
    hard_hit_value = _safe_int(hard_hits)
    barrel_value = _safe_int(barrels)
    walks_value = _safe_int(walks)
    strikeout_value = _safe_int(strikeouts)
    pitches_seen_value = _safe_int(pitches_seen)

    killers: list[str] = []

    if plate_appearance_value < 6:
        return "NOT READY", 0.0, killers

    hard_hit_rate = hard_hit_value / max(
        plate_appearance_value,
        1,
    )
    strikeout_rate = strikeout_value / max(
        plate_appearance_value,
        1,
    )
    pitches_per_plate_appearance = (
        pitches_seen_value / plate_appearance_value
        if pitches_seen_value > 0
        else 0.0
    )

    if strikeout_rate >= 0.40:
        killers.append("Favored offense is striking out at an extreme rate.")

    if (
        hard_hit_rate >= 0.25
        or barrel_value >= 1
        or walks_value >= 2
        or pitches_per_plate_appearance >= 4.2
    ):
        return "STRENGTHENING", 20.0, killers

    if (
        hard_hit_rate >= 0.12
        or walks_value >= 1
        or pitches_per_plate_appearance >= 3.7
    ):
        return "INTACT", 9.0, killers

    if strikeout_rate >= 0.30:
        return "WEAKENING", -10.0, killers

    if hard_hit_value == 0 and walks_value == 0:
        return "WEAKENING", -12.0, killers

    return "INTACT", 4.0, killers


def grade_bullpen_outlook(
    *,
    favored_starter_still_active: bool,
    favored_starter_pitch_count: int | None,
    inning: int | None,
    favored_bullpen_status: str | None,
    opponent_bullpen_status: str | None,
    favored_key_reliever_unavailable: bool = False,
    opponent_starter_removed: bool = False,
) -> tuple[str, float, list[str]]:
    inning_value = _safe_int(inning)
    pitch_count_value = _safe_int(favored_starter_pitch_count)

    favored_status = (
        str(favored_bullpen_status or "UNKNOWN")
        .strip()
        .upper()
    )
    opponent_status = (
        str(opponent_bullpen_status or "UNKNOWN")
        .strip()
        .upper()
    )

    killers: list[str] = []

    if favored_key_reliever_unavailable:
        killers.append("Key favored-team reliever is unavailable.")

    if not favored_starter_still_active and inning_value <= 3:
        killers.append("Favored starter exited earlier than planned.")

    if favored_status == "COMPROMISED":
        killers.append("Favored bullpen is compromised.")

    if favored_key_reliever_unavailable:
        return "COMPROMISED", -15.0, killers

    if favored_status == "COMPROMISED":
        return "COMPROMISED", -15.0, killers

    if not favored_starter_still_active and inning_value <= 3:
        return "COMPROMISED", -15.0, killers

    if (
        opponent_starter_removed
        and opponent_status in {"LIMITED", "COMPROMISED"}
    ):
        return "STRENGTHENING", 15.0, killers

    if favored_status == "FULLY AVAILABLE":
        return "FULLY AVAILABLE", 12.0, killers

    if favored_status == "MOSTLY AVAILABLE":
        return "MOSTLY AVAILABLE", 7.0, killers

    if favored_status == "LIMITED":
        return "LIMITED", -8.0, killers

    if pitch_count_value >= 80 and inning_value <= 4:
        return "LIMITED", -8.0, killers

    return "UNKNOWN", 0.0, killers


def grade_game_state(
    *,
    favored_team_is_home: bool,
    favored_score: int | None,
    opponent_score: int | None,
    inning: int | None,
) -> tuple[str, float]:
    favored_score_value = _safe_int(favored_score)
    opponent_score_value = _safe_int(opponent_score)
    inning_value = _safe_int(inning)

    run_difference = favored_score_value - opponent_score_value

    if inning_value <= 3:
        if run_difference >= 2:
            return "FAVORABLE EARLY", 8.0

        if run_difference >= -1:
            return "PLAYABLE EARLY", 5.0

        if run_difference == -2:
            return "PRESSURED EARLY", -5.0

        return "UNFAVORABLE EARLY", -10.0

    if inning_value <= 6:
        if run_difference >= 2:
            return "FAVORABLE MIDGAME", 8.0

        if run_difference >= 0:
            return "PLAYABLE MIDGAME", 5.0

        if run_difference == -1:
            return "PRESSURED MIDGAME", -4.0

        if run_difference == -2:
            return "UNFAVORABLE MIDGAME", -8.0

        return "STRUCTURALLY POOR", -10.0

    if run_difference > 0:
        return "FAVORABLE LATE", 8.0

    if run_difference == 0:
        return "PLAYABLE LATE", 3.0

    if run_difference == -1 and favored_team_is_home:
        return "PRESSURED LATE", -6.0

    return "STRUCTURALLY POOR", -10.0


def grade_feed_confidence(
    feed_status: str,
) -> tuple[str, float]:
    normalized_status = str(feed_status or "").strip().upper()

    if normalized_status == FEED_CURRENT:
        return FEED_CURRENT, 5.0

    if normalized_status == FEED_STALE:
        return FEED_STALE, -5.0

    return FEED_CONFLICT, -5.0


def classify_thesis_status(
    thesis_score: float,
    *,
    sample_ready: bool,
    active_thesis_killers: list[str],
) -> str:
    severe_killer_terms = (
        "multiple barrels",
        "three early walks",
        "exited earlier",
        "compromised",
        "key favored-team reliever",
        "extreme rate",
    )

    severe_killer_active = any(
        any(
            term in killer.lower()
            for term in severe_killer_terms
        )
        for killer in active_thesis_killers
    )

    if severe_killer_active or thesis_score <= -35:
        return THESIS_INVALIDATED

    if not sample_ready:
        return THESIS_NOT_READY

    if thesis_score >= 35:
        return THESIS_STRENGTHENING

    if thesis_score >= 10:
        return THESIS_INTACT

    if thesis_score <= -10:
        return THESIS_WEAKENING

    return THESIS_NOT_READY


def classify_price_status(
    *,
    current_odds: int | None,
    target_odds: int | None,
    maximum_odds: int | None,
    thesis_status: str,
) -> str:
    if (
        current_odds is None
        or target_odds is None
        or maximum_odds is None
    ):
        return PRICE_NOT_AVAILABLE

    current_value = int(current_odds)
    target_value = int(target_odds)
    maximum_value = int(maximum_odds)

    improvement_from_target = price_improvement_points(
        current_value,
        target_value,
    )

    target_reached = odds_are_equal_or_better(
        current_value,
        target_value,
    )

    maximum_reached = odds_are_equal_or_better(
        current_value,
        maximum_value,
    )

    if not maximum_reached:
        return PRICE_WORSE_THAN_MAXIMUM

    if target_reached:
        if improvement_from_target >= 5:
            if thesis_status in {
                THESIS_WEAKENING,
                THESIS_INVALIDATED,
            }:
                return PRICE_SUSPICIOUS_DISCOUNT

            return PRICE_SIGNIFICANT_DISCOUNT

        return PRICE_TARGET_REACHED

    return PRICE_ACCEPTABLE


def select_live_decision(
    *,
    feed_status: str,
    thesis_status: str,
    price_status: str,
    game_state_status: str,
    active_thesis_killers: list[str],
) -> str:
    normalized_feed = str(feed_status or "").strip().upper()

    if normalized_feed != FEED_CURRENT:
        return DECISION_DATA_CHECK

    if thesis_status == THESIS_INVALIDATED:
        return DECISION_EXIT_THESIS

    if game_state_status == "STRUCTURALLY POOR":
        return DECISION_PASS

    if price_status == PRICE_SUSPICIOUS_DISCOUNT:
        return DECISION_PASS

    if thesis_status == THESIS_WEAKENING:
        return DECISION_PASS

    if thesis_status == THESIS_NOT_READY:
        return DECISION_WATCH

    if price_status in {
        PRICE_TARGET_REACHED,
        PRICE_SIGNIFICANT_DISCOUNT,
        PRICE_ACCEPTABLE,
    }:
        if thesis_status in {
            THESIS_INTACT,
            THESIS_STRENGTHENING,
        }:
            if not active_thesis_killers:
                return DECISION_ENTER_CONSIDERATION

    if price_status == PRICE_WORSE_THAN_MAXIMUM:
        return DECISION_WATCH

    return DECISION_WATCH


def build_trigger_reason(
    *,
    thesis_status: str,
    starter_command_status: str,
    contact_quality_status: str,
    offense_status: str,
    bullpen_status: str,
    price_status: str,
) -> str:
    reasons: list[str] = []

    if starter_command_status == "STRONG":
        reasons.append("Favored starter command is strong.")
    elif starter_command_status == "ACCEPTABLE":
        reasons.append("Favored starter command remains acceptable.")

    if contact_quality_status == "STRONG":
        reasons.append("Opponent contact quality is limited.")
    elif contact_quality_status == "ACCEPTABLE":
        reasons.append("Contact quality remains manageable.")

    if offense_status == "STRENGTHENING":
        reasons.append("Favored offense is producing encouraging process.")
    elif offense_status == "INTACT":
        reasons.append("Favored offense remains competitive.")

    if bullpen_status == "STRENGTHENING":
        reasons.append("Bullpen outlook has improved.")
    elif bullpen_status in {
        "FULLY AVAILABLE",
        "MOSTLY AVAILABLE",
    }:
        reasons.append("Favored bullpen remains available.")

    if price_status in {
        PRICE_TARGET_REACHED,
        PRICE_SIGNIFICANT_DISCOUNT,
    }:
        reasons.append("The live price has reached the saved target.")

    if not reasons:
        if thesis_status == THESIS_NOT_READY:
            return "More live data is required before grading the thesis."

        return "Live evidence is mixed."

    return " ".join(reasons)


def build_warning_reason(
    *,
    starter_command_status: str,
    contact_quality_status: str,
    offense_status: str,
    bullpen_status: str,
    price_status: str,
    game_state_status: str,
    active_thesis_killers: list[str],
) -> str:
    warnings: list[str] = []

    if starter_command_status in {"WEAKENING", "FAILURE"}:
        warnings.append("Favored starter command is deteriorating.")

    if contact_quality_status in {"WEAKENING", "FAILURE"}:
        warnings.append("Opponent contact quality is concerning.")

    if offense_status == "WEAKENING":
        warnings.append("Favored offensive process is weakening.")

    if bullpen_status in {"LIMITED", "COMPROMISED"}:
        warnings.append("Favored bullpen outlook is unfavorable.")

    if price_status == PRICE_WORSE_THAN_MAXIMUM:
        warnings.append("The live price is still worse than the maximum acceptable price.")

    if price_status == PRICE_SUSPICIOUS_DISCOUNT:
        warnings.append(
            "The price improved while the thesis deteriorated."
        )

    if game_state_status == "STRUCTURALLY POOR":
        warnings.append(
            "The current inning and score make the original market structurally unattractive."
        )

    if active_thesis_killers:
        warnings.append(
            "Active thesis killers: "
            + "; ".join(active_thesis_killers)
        )

    if not warnings:
        return ""

    return " ".join(warnings)


def evaluate_live_thesis(
    *,
    feed_status: str,

    target_odds: int | None,
    maximum_odds: int | None,
    current_live_odds: int | None,

    pitch_count: int | None,
    strikes: int | None,
    first_pitch_strike_rate: float | None,
    pitcher_walks: int | None,
    batters_faced: int | None,

    pitcher_hard_hits_allowed: int | None,
    pitcher_barrels_allowed: int | None,
    balls_in_play_against_pitcher: int | None,

    favored_plate_appearances: int | None,
    favored_hard_hits: int | None,
    favored_barrels: int | None,
    favored_walks: int | None,
    favored_strikeouts: int | None,
    favored_pitches_seen: int | None,

    favored_starter_still_active: bool,
    inning: int | None,
    favored_bullpen_status: str | None,
    opponent_bullpen_status: str | None,
    favored_key_reliever_unavailable: bool,
    opponent_starter_removed: bool,

    favored_team_is_home: bool,
    favored_score: int | None,
    opponent_score: int | None,
) -> dict[str, Any]:
    command_status, command_score, command_killers = (
        grade_starter_command(
            pitch_count=pitch_count,
            strikes=strikes,
            first_pitch_strike_rate=first_pitch_strike_rate,
            walks=pitcher_walks,
            batters_faced=batters_faced,
        )
    )

    contact_status, contact_score, contact_killers = (
        grade_contact_quality(
            hard_hits=pitcher_hard_hits_allowed,
            barrels=pitcher_barrels_allowed,
            balls_in_play=balls_in_play_against_pitcher,
        )
    )

    offense_status, offense_score, offense_killers = (
        grade_offensive_process(
            plate_appearances=favored_plate_appearances,
            hard_hits=favored_hard_hits,
            barrels=favored_barrels,
            walks=favored_walks,
            strikeouts=favored_strikeouts,
            pitches_seen=favored_pitches_seen,
        )
    )

    bullpen_status, bullpen_score, bullpen_killers = (
        grade_bullpen_outlook(
            favored_starter_still_active=(
                favored_starter_still_active
            ),
            favored_starter_pitch_count=pitch_count,
            inning=inning,
            favored_bullpen_status=favored_bullpen_status,
            opponent_bullpen_status=opponent_bullpen_status,
            favored_key_reliever_unavailable=(
                favored_key_reliever_unavailable
            ),
            opponent_starter_removed=opponent_starter_removed,
        )
    )

    game_state_status, game_state_score = grade_game_state(
        favored_team_is_home=favored_team_is_home,
        favored_score=favored_score,
        opponent_score=opponent_score,
        inning=inning,
    )

    normalized_feed_status, feed_score = grade_feed_confidence(
        feed_status
    )

    score_components = {
        "starter_command": command_score,
        "contact_quality": contact_score,
        "offensive_process": offense_score,
        "bullpen_outlook": bullpen_score,
        "game_state": game_state_score,
        "feed_confidence": feed_score,
    }

    thesis_score = round(
        sum(score_components.values()),
        3,
    )

    active_thesis_killers = list(
        dict.fromkeys(
            command_killers
            + contact_killers
            + offense_killers
            + bullpen_killers
        )
    )

    sample_ready = (
        command_status != "NOT READY"
        and offense_status != "NOT READY"
    )

    thesis_status = classify_thesis_status(
        thesis_score,
        sample_ready=sample_ready,
        active_thesis_killers=active_thesis_killers,
    )

    price_status = classify_price_status(
        current_odds=current_live_odds,
        target_odds=target_odds,
        maximum_odds=maximum_odds,
        thesis_status=thesis_status,
    )

    decision = select_live_decision(
        feed_status=normalized_feed_status,
        thesis_status=thesis_status,
        price_status=price_status,
        game_state_status=game_state_status,
        active_thesis_killers=active_thesis_killers,
    )

    trigger_reason = build_trigger_reason(
        thesis_status=thesis_status,
        starter_command_status=command_status,
        contact_quality_status=contact_status,
        offense_status=offense_status,
        bullpen_status=bullpen_status,
        price_status=price_status,
    )

    warning_reason = build_warning_reason(
        starter_command_status=command_status,
        contact_quality_status=contact_status,
        offense_status=offense_status,
        bullpen_status=bullpen_status,
        price_status=price_status,
        game_state_status=game_state_status,
        active_thesis_killers=active_thesis_killers,
    )

    result = LiveThesisResult(
        starter_command_status=command_status,
        contact_quality_status=contact_status,
        offense_status=offense_status,
        bullpen_status=bullpen_status,
        thesis_score=thesis_score,
        thesis_status=thesis_status,
        price_status=price_status,
        decision=decision,
        trigger_reason=trigger_reason,
        warning_reason=warning_reason,
        active_thesis_killers=active_thesis_killers,
        score_components={
            **score_components,
            "game_state_status": game_state_status,
        },
    )

    return result.to_dict()

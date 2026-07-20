from __future__ import annotations

from dataclasses import dataclass


def implied_probability(american_odds: int) -> float:
    if american_odds == 0:
        raise ValueError("American odds cannot be zero.")
    if american_odds > 0:
        return 100 / (american_odds + 100)
    return abs(american_odds) / (abs(american_odds) + 100)


def no_vig_probabilities(first_odds: int, second_odds: int) -> tuple[float, float, float]:
    first_raw = implied_probability(first_odds)
    second_raw = implied_probability(second_odds)
    total = first_raw + second_raw
    if total <= 0:
        raise ValueError("Two-sided market probabilities must sum to more than zero.")
    return first_raw / total, second_raw / total, total - 1


def decimal_odds(american_odds: int) -> float:
    if american_odds > 0:
        return 1 + american_odds / 100
    return 1 + 100 / abs(american_odds)


def expected_value_per_dollar(probability: float, american_odds: int) -> float:
    """Only use when probability comes from a calibrated model or explicit user estimate."""
    payout_profit = decimal_odds(american_odds) - 1
    return probability * payout_profit - (1 - probability)


def validate_price_band(target_odds: int, maximum_odds: int) -> None:
    # A larger American-odds number is always a better bettor price: -130 > -140 and +140 > +125.
    if target_odds < maximum_odds:
        raise ValueError(
            "Target price must be equal to or better than the maximum acceptable price "
            "(for example, target -135 and maximum -140)."
        )


@dataclass(frozen=True)
class DecisionResult:
    recommendation: str
    lifecycle_status: str
    price_status: str
    rationale: str


def classify_decision(
    *,
    selection: str,
    research_lean: str,
    confidence: str,
    readiness: str,
    current_odds: int,
    target_odds: int,
    maximum_odds: int,
) -> DecisionResult:
    validate_price_band(target_odds, maximum_odds)

    if research_lean in {"No reliable advantage", ""}:
        return DecisionResult(
            "PASS",
            "PRICE REJECTED",
            "NO RESEARCH LEAN",
            "The current research layer does not identify a reliable side advantage.",
        )

    if selection != research_lean:
        return DecisionResult(
            "PASS",
            "PRICE REJECTED",
            "MISALIGNED",
            f"The selected side does not match the current research lean ({research_lean}).",
        )

    if confidence == "Low" or readiness == "DATA CHECK":
        return DecisionResult(
            "DATA CHECK",
            "MARKET REVIEWED",
            "INSUFFICIENT INFORMATION",
            "The price may be available, but the underlying matchup information is incomplete.",
        )

    if current_odds >= target_odds:
        return DecisionResult(
            "TARGET REACHED",
            "PRICE ACCEPTED",
            "TARGET OR BETTER",
            "The current price meets or beats the preferred entry target. This is an evaluation signal, not an automatic wager.",
        )

    if current_odds >= maximum_odds:
        return DecisionResult(
            "ENTER CONSIDERATION",
            "PRICE ACCEPTED",
            "ACCEPTABLE BAND",
            "The current price is inside the acceptable band but has not reached the preferred target.",
        )

    return DecisionResult(
        "WAIT",
        "WAITING",
        "TOO EXPENSIVE",
        "The current price is worse than the maximum acceptable entry. Continue monitoring or pass.",
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MarketPrice:
    american_odds: int

    @property
    def implied_probability(self) -> float:
        if self.american_odds < 0:
            return abs(self.american_odds) / (abs(self.american_odds) + 100)
        return 100 / (self.american_odds + 100)


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def build_strategy_packet(
    item: dict,
    market: str,
    away_odds: int | None,
    home_odds: int | None,
    notes: str,
    market_status: str,
) -> str:
    d = item["details"]
    odds_submitted = away_odds is not None and home_odds is not None

    if odds_submitted:
        away_raw = MarketPrice(int(away_odds)).implied_probability
        home_raw = MarketPrice(int(home_odds)).implied_probability
        total = away_raw + home_raw
        market_block = (
            f"Market: {market}\n"
            f"{item['away']}: {away_odds:+d} ({away_raw / total:.1%} no-vig)\n"
            f"{item['home']}: {home_odds:+d} ({home_raw / total:.1%} no-vig)\n"
            f"Market hold: {total - 1:.1%}"
        )
    else:
        market_block = "No sportsbook prices submitted. Market value is unknown."

    missing = []
    for label, key in [
        ("Away starter stats", "away_starter"),
        ("Home starter stats", "home_starter"),
        ("Away season offense", "away_offense"),
        ("Home season offense", "home_offense"),
    ]:
        if not item["component_availability"].get(key):
            missing.append(label)

    missing_text = ", ".join(missing) if missing else "None in Phase 1 automated components"

    return f"""MLB TRADING DESK — STRATEGY PACKET

GAME
{item['matchup']}

RETRIEVED DATA
Probable starters: {item['away_starter']} vs {item['home_starter']}
Starter season data: {'Complete' if item['component_availability']['away_starter'] and item['component_availability']['home_starter'] else 'Incomplete'}
Season offense baseline: {'Complete' if item['component_availability']['away_offense'] and item['component_availability']['home_offense'] else 'Incomplete'}

INFERRED APP OUTPUT
Premarket status: {item['premarket_status']}
Market status: {market_status}
Matchup Separation Score: {fmt(item['separation_score'], 1)}/100
Data confidence: {item['confidence']} ({item['completeness']}% complete)
Baseball-side advantage: {item['baseball_advantage']}

STARTING PITCHING — RETRIEVED SEASON DATA
Away: {item['away_starter']} | score {fmt(item['away_sp_score'], 1)}
Home: {item['home_starter']} | score {fmt(item['home_sp_score'], 1)}
Away ERA / WHIP / K9 / BB9: {fmt(d.get('Away_ERA'))} / {fmt(d.get('Away_WHIP'))} / {fmt(d.get('Away_K9'))} / {fmt(d.get('Away_BB9'))}
Home ERA / WHIP / K9 / BB9: {fmt(d.get('Home_ERA'))} / {fmt(d.get('Home_WHIP'))} / {fmt(d.get('Home_K9'))} / {fmt(d.get('Home_BB9'))}

SEASON OFFENSE BASELINE — RETRIEVED DATA
Away score: {fmt(item['away_off_score'], 1)} | OPS {fmt(d.get('Away_OPS'), 3)} | K% {fmt(d.get('Away_K%'), 1)} | BB% {fmt(d.get('Away_BB%'), 1)}
Home score: {fmt(item['home_off_score'], 1)} | OPS {fmt(d.get('Home_OPS'), 3)} | K% {fmt(d.get('Home_K%'), 1)} | BB% {fmt(d.get('Home_BB%'), 1)}

MISSING OR NOT YET AUTOMATED
Phase 1 missing data: {missing_text}
Confirmed lineups: {item['lineup_status']}
Bullpen workload: {item['bullpen_status']}
Injuries / late scratches: Not integrated
Handedness and recent-form splits: Not integrated

MANUALLY ENTERED MARKET DATA
{market_block}

USER-ENTERED CONTEXT
{notes or 'None entered'}

STRATEGY THREAD QUESTIONS
1. Does the baseball-side advantage remain valid after lineups, handedness, bullpen, injuries, and price?
2. Is F5 or full game the better expression?
3. What is the maximum acceptable price?
4. Should this be pregame, live watch, or pass?
5. What live conditions cancel or confirm the thesis?
"""

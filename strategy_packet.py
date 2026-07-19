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

    return f"""MLB TRADING DESK — STRATEGY PACKET v0.5

GAME
{item['matchup']}

INFERRED APP OUTPUT
Premarket status: {item['premarket_status']}
Readiness: {item['readiness']}
Market status: {market_status}
Matchup Separation Score: {fmt(item['separation_score'], 1)}/100
Data confidence: {item['confidence']} ({item['completeness']}% complete)
Baseball-side advantage: {item['baseball_advantage']}

STARTING PITCHING — RETRIEVED DATA
Away: {item['away_starter']} ({item['away_pitch_hand']}) | season score {fmt(item['away_sp_score'], 1)} | recent-30 score {fmt(item['away_pitcher_recent30_score'], 1)}
Home: {item['home_starter']} ({item['home_pitch_hand']}) | season score {fmt(item['home_sp_score'], 1)} | recent-30 score {fmt(item['home_pitcher_recent30_score'], 1)}
Away ERA / WHIP / K9 / BB9: {fmt(d.get('Away_ERA'))} / {fmt(d.get('Away_WHIP'))} / {fmt(d.get('Away_K9'))} / {fmt(d.get('Away_BB9'))}
Home ERA / WHIP / K9 / BB9: {fmt(d.get('Home_ERA'))} / {fmt(d.get('Home_WHIP'))} / {fmt(d.get('Home_K9'))} / {fmt(d.get('Home_BB9'))}

OFFENSE MATCHUP — RETRIEVED DATA
Away season baseline: {fmt(item['away_off_score'], 1)}
Away vs {item['home_pitch_hand']}HP: {fmt(item['away_split_score'], 1)}
Away matchup-adjusted: {fmt(item['away_matchup_off_score'], 1)}
Away recent 14 / 30: {fmt(item['away_recent14_score'], 1)} / {fmt(item['away_recent30_score'], 1)} ({item['away_recent_trend']})

Home season baseline: {fmt(item['home_off_score'], 1)}
Home vs {item['away_pitch_hand']}HP: {fmt(item['home_split_score'], 1)}
Home matchup-adjusted: {fmt(item['home_matchup_off_score'], 1)}
Home recent 14 / 30: {fmt(item['home_recent14_score'], 1)} / {fmt(item['home_recent30_score'], 1)} ({item['home_recent_trend']})

LINEUP READINESS
Status: {item['lineup_status']}
Away lineup entries: {item['away_lineup_count']}
Home lineup entries: {item['home_lineup_count']}

BULLPEN AVAILABILITY — PRIOR THREE DAYS
Away status: {item['away_bullpen']['status']}
Away games / relief pitches / multi-day arms: {item['away_bullpen']['games_found']} / {item['away_bullpen']['team_pitches']} / {item['away_bullpen']['multi_day_arms']}
Home status: {item['home_bullpen']['status']}
Home games / relief pitches / multi-day arms: {item['home_bullpen']['games_found']} / {item['home_bullpen']['team_pitches']} / {item['home_bullpen']['multi_day_arms']}
Full-game context: {item['full_game_context']}

NOT YET AUTOMATED
Injuries / late scratches: Not integrated
Automated sportsbook odds: Not integrated

MANUALLY ENTERED MARKET DATA
{market_block}

USER-ENTERED CONTEXT
{notes or 'None entered'}

STRATEGY THREAD QUESTIONS
1. Is the baseball-side advantage supported by the handedness matchup and current lineups?
2. Does recent form meaningfully reinforce or contradict the season baseline?
3. Does bullpen availability make F5 or full game the better expression?
4. What is the maximum acceptable price?
5. Should this be pregame, live watch, or pass?
6. What live conditions cancel or confirm the thesis?
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketPrice:
    american_odds: int

    @property
    def implied_probability(self) -> float:
        if self.american_odds < 0:
            return abs(self.american_odds) / (abs(self.american_odds) + 100)
        return 100 / (self.american_odds + 100)


def build_strategy_packet(item: dict, market: str, away_odds: int, home_odds: int, notes: str) -> str:
    away_raw, home_raw = MarketPrice(away_odds).implied_probability, MarketPrice(home_odds).implied_probability
    total, d = away_raw + home_raw, item["details"]
    return f"""MLB TRADING DESK — STRATEGY PACKET

GAME
{item['matchup']}

APP STATUS
{item['classification']}

RESEARCH PRIORITY
{item['research_score']}/100

DATA CONFIDENCE
{item['confidence']} ({item['completeness']}% complete)

PRELIMINARY LEAN
{item['lean']}

STARTING PITCHING
Away: {item['away_starter']} — score {item['away_sp_score']}
Home: {item['home_starter']} — score {item['home_sp_score']}
Away ERA / WHIP / K9: {d.get('Away_ERA', 0):.2f} / {d.get('Away_WHIP', 0):.2f} / {d.get('Away_K9', 0):.2f}
Home ERA / WHIP / K9: {d.get('Home_ERA', 0):.2f} / {d.get('Home_WHIP', 0):.2f} / {d.get('Home_K9', 0):.2f}

OFFENSE
Away score: {item['away_off_score']} | OPS {d.get('Away_OPS', 0):.3f} | K% {d.get('Away_K%', 0):.1f} | BB% {d.get('Away_BB%', 0):.1f}
Home score: {item['home_off_score']} | OPS {d.get('Home_OPS', 0):.3f} | K% {d.get('Home_K%', 0):.1f} | BB% {d.get('Home_BB%', 0):.1f}

DATA GAPS
Lineups: {item['lineup_status']}
Bullpen: {item['bullpen_status']}

MARKET INPUT
Market: {market}
{item['away']}: {away_odds:+d} ({away_raw / total:.1%} no-vig)
{item['home']}: {home_odds:+d} ({home_raw / total:.1%} no-vig)

USER NOTES / SCREENSHOT CONTEXT
{notes or 'None entered'}

STRATEGY THREAD QUESTIONS
1. Is the preliminary lean supported after lineups, bullpen, injuries, and price?
2. Is F5 or full game the better expression?
3. What is the maximum acceptable price?
4. Should this be pregame, live watch, or pass?
5. What live conditions cancel or confirm the thesis?
"""

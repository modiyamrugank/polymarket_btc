"""Bet tracking and performance monitoring."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import structlog

from .candle_analyzer import Signal
from .polymarket_client import BetResult, Market

logger = structlog.get_logger()

# Default log file path
LOG_FILE = Path("bet_history.json")


@dataclass
class BetRecord:
    """Record of a single bet."""

    timestamp: str
    signal: str
    market_question: str
    market_end_time: str
    side: str  # "Yes" or "No"
    amount: float
    entry_price: float
    simulated: bool
    candle_1_color: str
    candle_2_color: str
    outcome: Optional[str] = None  # "WIN", "LOSS", or None if pending
    pnl: Optional[float] = None  # Profit/loss in USDC

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BetRecord":
        return cls(**data)


@dataclass
class PerformanceStats:
    """Performance statistics."""

    total_bets: int
    wins: int
    losses: int
    pending: int
    win_rate: float
    total_pnl: float
    simulated_bets: int
    live_bets: int

    def __str__(self) -> str:
        return (
            f"Performance Stats:\n"
            f"  Total Bets: {self.total_bets} ({self.simulated_bets} simulated, {self.live_bets} live)\n"
            f"  Wins: {self.wins} | Losses: {self.losses} | Pending: {self.pending}\n"
            f"  Win Rate: {self.win_rate:.1%}\n"
            f"  Total P&L: ${self.total_pnl:+.2f}"
        )


class BetTracker:
    """Tracks bets and calculates performance metrics."""

    def __init__(self, log_file: Path = LOG_FILE):
        self.log_file = log_file
        self.records: list[BetRecord] = []
        self._load_history()

    def _load_history(self):
        """Load bet history from file."""
        if self.log_file.exists():
            try:
                with open(self.log_file, "r") as f:
                    data = json.load(f)
                    self.records = [BetRecord.from_dict(r) for r in data]
                logger.info("loaded_bet_history", count=len(self.records))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("failed_to_load_history", error=str(e))
                self.records = []
        else:
            self.records = []

    def _save_history(self):
        """Save bet history to file."""
        try:
            with open(self.log_file, "w") as f:
                json.dump([r.to_dict() for r in self.records], f, indent=2)
            logger.debug("saved_bet_history", count=len(self.records))
        except IOError as e:
            logger.error("failed_to_save_history", error=str(e))

    def record_bet(
        self,
        signal: Signal,
        market: Market,
        bet_result: BetResult,
        candle_1_color: str,
        candle_2_color: str,
    ) -> BetRecord:
        """
        Record a new bet.

        Args:
            signal: The trading signal that triggered this bet
            market: The market being bet on
            bet_result: Result from placing the bet
            candle_1_color: Color of the first candle
            candle_2_color: Color of the second candle

        Returns:
            The created BetRecord
        """
        record = BetRecord(
            timestamp=datetime.now().isoformat(),
            signal=signal.value,
            market_question=market.question,
            market_end_time=market.end_date.isoformat(),
            side=bet_result.side,
            amount=bet_result.amount,
            entry_price=bet_result.price,
            simulated=bet_result.simulated,
            candle_1_color=candle_1_color,
            candle_2_color=candle_2_color,
        )

        self.records.append(record)
        self._save_history()

        logger.info(
            "bet_recorded",
            signal=signal.value,
            side=bet_result.side,
            amount=bet_result.amount,
            simulated=bet_result.simulated,
        )

        return record

    def record_skip(
        self,
        signal: Signal,
        candle_1_color: str,
        candle_2_color: str,
        reason: str,
    ):
        """Log a skipped bet (for monitoring purposes)."""
        logger.info(
            "bet_skipped",
            signal=signal.value,
            candle_1=candle_1_color,
            candle_2=candle_2_color,
            reason=reason,
        )

    def update_outcome(
        self,
        record_index: int,
        outcome: str,
        final_price: float,
    ):
        """
        Update the outcome of a bet.

        Args:
            record_index: Index of the record to update
            outcome: "WIN" or "LOSS"
            final_price: Final settlement price
        """
        if 0 <= record_index < len(self.records):
            record = self.records[record_index]
            record.outcome = outcome

            # Calculate P&L
            if outcome == "WIN":
                # Won: receive (1 - entry_price) * amount worth of payout
                record.pnl = (1 - record.entry_price) * record.amount
            else:
                # Lost: lose the bet amount
                record.pnl = -record.amount

            self._save_history()
            logger.info(
                "outcome_updated",
                outcome=outcome,
                pnl=record.pnl,
            )

    def get_stats(self) -> PerformanceStats:
        """Calculate performance statistics."""
        total = len(self.records)
        wins = sum(1 for r in self.records if r.outcome == "WIN")
        losses = sum(1 for r in self.records if r.outcome == "LOSS")
        pending = sum(1 for r in self.records if r.outcome is None)
        simulated = sum(1 for r in self.records if r.simulated)
        live = total - simulated

        win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0
        total_pnl = sum(r.pnl for r in self.records if r.pnl is not None)

        return PerformanceStats(
            total_bets=total,
            wins=wins,
            losses=losses,
            pending=pending,
            win_rate=win_rate,
            total_pnl=total_pnl,
            simulated_bets=simulated,
            live_bets=live,
        )

    def get_recent_bets(self, n: int = 10) -> list[BetRecord]:
        """Get the n most recent bets."""
        return self.records[-n:]

    def print_summary(self):
        """Print a summary of recent performance."""
        stats = self.get_stats()
        print("\n" + "=" * 50)
        print(stats)
        print("=" * 50)

        recent = self.get_recent_bets(5)
        if recent:
            print("\nRecent Bets:")
            for record in recent:
                status = record.outcome or "PENDING"
                mode = "SIM" if record.simulated else "LIVE"
                pnl_str = f"${record.pnl:+.2f}" if record.pnl else "N/A"
                print(
                    f"  [{mode}] {record.timestamp[:16]} | {record.signal} → {record.side} "
                    f"@ {record.entry_price:.2f} | {status} | P&L: {pnl_str}"
                )
        print()


# Global tracker instance
bet_tracker = BetTracker()

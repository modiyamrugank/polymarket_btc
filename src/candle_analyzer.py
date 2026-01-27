"""Candle analysis logic for generating trading signals."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import structlog

from .price_fetcher import Candle

logger = structlog.get_logger()


class Signal(Enum):
    """Trading signal types."""

    UP = "UP"  # Bet on BTC going up
    DOWN = "DOWN"  # Bet on BTC going down
    SKIP = "SKIP"  # No bet


@dataclass
class SignalResult:
    """Result of candle analysis."""

    signal: Signal
    candle_1: Candle  # Second-to-last candle
    candle_2: Candle  # Last candle
    reason: str

    def __str__(self) -> str:
        return (
            f"Signal: {self.signal.value} | "
            f"Candles: {self.candle_1.color}-{self.candle_2.color} | "
            f"Reason: {self.reason}"
        )


def analyze_candles(candle_1: Candle, candle_2: Candle) -> SignalResult:
    """
    Analyze two consecutive candles to generate a trading signal.

    Rules:
    - Two GREEN candles → BET UP
    - Two RED candles → BET DOWN
    - Mixed colors (GREEN-RED or RED-GREEN) → SKIP

    Args:
        candle_1: The second-to-last closed candle
        candle_2: The last closed candle

    Returns:
        SignalResult with the trading signal and reasoning
    """
    c1_green = candle_1.is_green
    c2_green = candle_2.is_green
    c1_red = candle_1.is_red
    c2_red = candle_2.is_red

    # Both green → UP
    if c1_green and c2_green:
        logger.info(
            "signal_generated",
            signal="UP",
            candle_1=candle_1.color,
            candle_2=candle_2.color,
        )
        return SignalResult(
            signal=Signal.UP,
            candle_1=candle_1,
            candle_2=candle_2,
            reason="Two consecutive GREEN candles indicate bullish momentum",
        )

    # Both red → DOWN
    if c1_red and c2_red:
        logger.info(
            "signal_generated",
            signal="DOWN",
            candle_1=candle_1.color,
            candle_2=candle_2.color,
        )
        return SignalResult(
            signal=Signal.DOWN,
            candle_1=candle_1,
            candle_2=candle_2,
            reason="Two consecutive RED candles indicate bearish momentum",
        )

    # Mixed signals → SKIP
    logger.info(
        "signal_generated",
        signal="SKIP",
        candle_1=candle_1.color,
        candle_2=candle_2.color,
    )
    return SignalResult(
        signal=Signal.SKIP,
        candle_1=candle_1,
        candle_2=candle_2,
        reason=f"Mixed candle colors ({candle_1.color}-{candle_2.color}), no clear trend",
    )


def get_signal_for_polymarket(signal: Signal) -> Optional[str]:
    """
    Convert a Signal to the Polymarket outcome string.

    Args:
        signal: The trading signal

    Returns:
        "Yes" for UP (BTC goes up), "No" for DOWN (BTC goes down), None for SKIP
    """
    if signal == Signal.UP:
        return "Yes"  # Betting that BTC will go UP
    elif signal == Signal.DOWN:
        return "No"  # Betting that BTC will go DOWN (or betting No on "Will BTC go up?")
    return None

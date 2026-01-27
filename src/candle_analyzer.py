"""Candle analysis logic for generating trading signals."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import structlog

from .price_fetcher import Candle
from .config import settings

logger = structlog.get_logger()


class Signal(Enum):
    """Trading signal types."""

    UP = "UP"  # Bet on BTC going up
    DOWN = "DOWN"  # Bet on BTC going down
    SKIP = "SKIP"  # No bet


@dataclass
class StrategyConfig:
    """Configuration for the trading strategy."""

    green_green: str = "UP"  # Action when both candles are green
    red_red: str = "DOWN"  # Action when both candles are red
    green_red: str = "SKIP"  # Action when green then red
    red_green: str = "SKIP"  # Action when red then green

    @classmethod
    def from_settings(cls) -> "StrategyConfig":
        """Create strategy config from global settings."""
        return cls(
            green_green=settings.green_green_action,
            red_red=settings.red_red_action,
            green_red=settings.green_red_action,
            red_green=settings.red_green_action,
        )

    @classmethod
    def momentum(cls) -> "StrategyConfig":
        """Momentum strategy: follow the trend."""
        return cls(
            green_green="UP",
            red_red="DOWN",
            green_red="SKIP",
            red_green="SKIP",
        )

    @classmethod
    def contrarian(cls) -> "StrategyConfig":
        """Contrarian strategy: bet against the trend."""
        return cls(
            green_green="DOWN",
            red_red="UP",
            green_red="SKIP",
            red_green="SKIP",
        )

    @classmethod
    def always_up(cls) -> "StrategyConfig":
        """Always bet UP when we have a clear signal."""
        return cls(
            green_green="UP",
            red_red="UP",
            green_red="SKIP",
            red_green="SKIP",
        )

    @classmethod
    def always_down(cls) -> "StrategyConfig":
        """Always bet DOWN when we have a clear signal."""
        return cls(
            green_green="DOWN",
            red_red="DOWN",
            green_red="SKIP",
            red_green="SKIP",
        )

    def describe(self) -> str:
        """Get a human-readable description."""
        return (
            f"GG→{self.green_green} | RR→{self.red_red} | "
            f"GR→{self.green_red} | RG→{self.red_green}"
        )


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


def _action_to_signal(action: str) -> Signal:
    """Convert action string to Signal enum."""
    if action == "UP":
        return Signal.UP
    elif action == "DOWN":
        return Signal.DOWN
    return Signal.SKIP


def analyze_candles(
    candle_1: Candle,
    candle_2: Candle,
    strategy: Optional[StrategyConfig] = None,
) -> SignalResult:
    """
    Analyze two consecutive candles to generate a trading signal.

    Args:
        candle_1: The second-to-last closed candle
        candle_2: The last closed candle
        strategy: Strategy configuration (defaults to settings-based config)

    Returns:
        SignalResult with the trading signal and reasoning
    """
    if strategy is None:
        strategy = StrategyConfig.from_settings()

    c1_green = candle_1.is_green
    c2_green = candle_2.is_green
    c1_red = candle_1.is_red
    c2_red = candle_2.is_red

    # Determine pattern and action
    if c1_green and c2_green:
        pattern = "GREEN-GREEN"
        action = strategy.green_green
        reason = f"Two GREEN candles → {action}"
    elif c1_red and c2_red:
        pattern = "RED-RED"
        action = strategy.red_red
        reason = f"Two RED candles → {action}"
    elif c1_green and c2_red:
        pattern = "GREEN-RED"
        action = strategy.green_red
        reason = f"GREEN then RED → {action}"
    elif c1_red and c2_green:
        pattern = "RED-GREEN"
        action = strategy.red_green
        reason = f"RED then GREEN → {action}"
    else:
        # DOJI cases
        pattern = f"{candle_1.color}-{candle_2.color}"
        action = "SKIP"
        reason = f"Unclear pattern ({pattern}) → SKIP"

    signal = _action_to_signal(action)

    logger.info(
        "signal_generated",
        signal=signal.value,
        pattern=pattern,
        candle_1=candle_1.color,
        candle_2=candle_2.color,
        strategy=strategy.describe(),
    )

    return SignalResult(
        signal=signal,
        candle_1=candle_1,
        candle_2=candle_2,
        reason=reason,
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

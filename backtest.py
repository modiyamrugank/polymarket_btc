#!/usr/bin/env python3
"""
Backtest the BTC 15-minute trading strategy.

Fetches historical 5-minute candle data from Binance and simulates
the trading strategy to calculate performance metrics.
"""

import argparse
import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


@dataclass
class Candle:
    """Represents a single candlestick."""
    open_time: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    close_time: datetime
    volume: float

    @property
    def is_green(self) -> bool:
        return self.close_price > self.open_price

    @property
    def is_red(self) -> bool:
        return self.close_price < self.open_price

    @property
    def color(self) -> str:
        if self.is_green:
            return "GREEN"
        elif self.is_red:
            return "RED"
        return "DOJI"


@dataclass
class StrategyConfig:
    """Configuration for the trading strategy."""

    green_green: str = "UP"  # Action when both candles are green
    red_red: str = "DOWN"  # Action when both candles are red
    green_red: str = "SKIP"  # Action when green then red
    red_green: str = "SKIP"  # Action when red then green

    @classmethod
    def momentum(cls) -> "StrategyConfig":
        """Momentum strategy: follow the trend."""
        return cls(green_green="UP", red_red="DOWN", green_red="SKIP", red_green="SKIP")

    @classmethod
    def contrarian(cls) -> "StrategyConfig":
        """Contrarian strategy: bet against the trend."""
        return cls(green_green="DOWN", red_red="UP", green_red="SKIP", red_green="SKIP")

    @classmethod
    def from_args(cls, gg: str, rr: str, gr: str, rg: str) -> "StrategyConfig":
        """Create from CLI arguments."""
        return cls(green_green=gg, red_red=rr, green_red=gr, red_green=rg)

    def describe(self) -> str:
        """Get a human-readable description."""
        return f"GG→{self.green_green} | RR→{self.red_red} | GR→{self.green_red} | RG→{self.red_green}"

    def get_action(self, c1_color: str, c2_color: str) -> str:
        """Get the action for a given candle pattern."""
        if c1_color == "GREEN" and c2_color == "GREEN":
            return self.green_green
        elif c1_color == "RED" and c2_color == "RED":
            return self.red_red
        elif c1_color == "GREEN" and c2_color == "RED":
            return self.green_red
        elif c1_color == "RED" and c2_color == "GREEN":
            return self.red_green
        return "SKIP"  # DOJI cases


@dataclass
class TradeResult:
    """Result of a single trade."""
    window_start: datetime
    candle_1_color: str
    candle_2_color: str
    signal: str  # "UP", "DOWN", "SKIP"
    candle_3_direction: str  # Actual direction of 3rd candle
    outcome: Optional[str]  # "WIN", "LOSS", or None for SKIP
    entry_price: float  # Price at bet time (candle 2 close)
    exit_price: float  # Price at resolution (candle 3 close)
    pnl_percent: float  # Percentage change


def generate_sample_candles(days: int = 7, seed: int = 42, momentum_factor: float = 0.1) -> list[Candle]:
    """
    Generate realistic sample candle data for offline backtesting.

    Uses a random walk with configurable momentum to simulate BTC price movement.

    Args:
        days: Number of days of data to generate
        seed: Random seed for reproducibility
        momentum_factor: How much momentum affects price (0 = pure random, 1 = strong momentum)
                        Default 0.1 for realistic BTC behavior
    """
    random.seed(seed)

    candles = []
    start_time = datetime.now() - timedelta(days=days)
    start_time = start_time.replace(minute=(start_time.minute // 5) * 5, second=0, microsecond=0)

    price = 100000.0  # Starting price
    volatility = 0.0015  # 0.15% per 5-min candle (realistic for BTC)
    momentum = 0.0

    num_candles = days * 24 * 12  # 12 candles per hour

    for i in range(num_candles):
        open_time = start_time + timedelta(minutes=5 * i)
        close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)

        # Random walk with weak momentum (more realistic)
        # Low momentum_factor means less trend continuation
        momentum = momentum * momentum_factor + random.gauss(0, 1) * (1 - momentum_factor)
        change = momentum * volatility * price

        open_price = price
        close_price = price + change

        # Add some noise for high/low
        high_price = max(open_price, close_price) + abs(random.gauss(0, volatility * price * 0.5))
        low_price = min(open_price, close_price) - abs(random.gauss(0, volatility * price * 0.5))

        candle = Candle(
            open_time=open_time,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            close_time=close_time,
            volume=random.uniform(100, 1000),
        )
        candles.append(candle)

        price = close_price

    return candles


async def fetch_historical_candles(
    days: int = 7,
    session: Optional[aiohttp.ClientSession] = None,
    offline: bool = False,
) -> list[Candle]:
    """Fetch historical 5-minute candles from Binance (or generate sample data if offline)."""

    # Use sample data if offline or aiohttp not available
    if offline or not AIOHTTP_AVAILABLE:
        print(f"Generating {days} days of sample candle data (offline mode)...")
        return generate_sample_candles(days=days)

    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        candles = []
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)

        # Binance limits to 1000 candles per request
        # 5-min candles = 288 per day, so we need multiple requests for > 3 days
        current_start = start_time

        print(f"Fetching {days} days of 5-minute candles from Binance...")

        while current_start < end_time:
            params = {
                "symbol": "BTCUSDT",
                "interval": "5m",
                "startTime": int(current_start.timestamp() * 1000),
                "endTime": int(end_time.timestamp() * 1000),
                "limit": 1000,
            }

            async with session.get(
                "https://api.binance.com/api/v3/klines",
                params=params
            ) as response:
                response.raise_for_status()
                data = await response.json()

                if not data:
                    break

                for kline in data:
                    candle = Candle(
                        open_time=datetime.fromtimestamp(kline[0] / 1000),
                        open_price=float(kline[1]),
                        high_price=float(kline[2]),
                        low_price=float(kline[3]),
                        close_price=float(kline[4]),
                        close_time=datetime.fromtimestamp(kline[6] / 1000),
                        volume=float(kline[5]),
                    )
                    candles.append(candle)

                # Move to next batch
                if data:
                    last_close_time = datetime.fromtimestamp(data[-1][6] / 1000)
                    current_start = last_close_time + timedelta(milliseconds=1)
                else:
                    break

                print(f"  Fetched {len(candles)} candles so far...")

                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)

        print(f"  Total: {len(candles)} candles")
        return candles

    finally:
        if own_session:
            await session.close()


def group_into_windows(candles: list[Candle]) -> list[tuple[Candle, Candle, Candle]]:
    """
    Group candles into 15-minute windows.

    Each window contains 3 consecutive 5-minute candles:
    - Candle 1: First 5 minutes (used for signal)
    - Candle 2: Second 5 minutes (used for signal)
    - Candle 3: Third 5 minutes (outcome)

    Returns list of (candle_1, candle_2, candle_3) tuples.
    """
    windows = []

    # Sort by open time
    sorted_candles = sorted(candles, key=lambda c: c.open_time)

    # Group into sets of 3 aligned to 15-minute boundaries
    i = 0
    while i < len(sorted_candles):
        candle = sorted_candles[i]

        # Check if this candle starts at a 15-minute boundary
        if candle.open_time.minute % 15 == 0:
            # Try to get the next 2 candles
            if i + 2 < len(sorted_candles):
                c1 = sorted_candles[i]
                c2 = sorted_candles[i + 1]
                c3 = sorted_candles[i + 2]

                # Verify they're consecutive
                if (c2.open_time - c1.open_time == timedelta(minutes=5) and
                    c3.open_time - c2.open_time == timedelta(minutes=5)):
                    windows.append((c1, c2, c3))
                    i += 3
                    continue

        i += 1

    return windows


def analyze_window(
    c1: Candle,
    c2: Candle,
    c3: Candle,
    strategy: StrategyConfig,
) -> TradeResult:
    """Analyze a 15-minute window and determine trade outcome."""

    # Determine signal based on first two candles and strategy
    signal = strategy.get_action(c1.color, c2.color)

    # Determine actual direction of third candle
    if c3.is_green:
        actual_direction = "UP"
    elif c3.is_red:
        actual_direction = "DOWN"
    else:
        actual_direction = "FLAT"

    # Determine outcome
    if signal == "SKIP":
        outcome = None
    elif signal == actual_direction:
        outcome = "WIN"
    elif actual_direction == "FLAT":
        # DOJI - count as loss since we didn't win
        outcome = "LOSS"
    else:
        outcome = "LOSS"

    # Calculate P&L percentage
    entry_price = c2.close_price
    exit_price = c3.close_price
    pnl_percent = ((exit_price - entry_price) / entry_price) * 100

    return TradeResult(
        window_start=c1.open_time,
        candle_1_color=c1.color,
        candle_2_color=c2.color,
        signal=signal,
        candle_3_direction=actual_direction,
        outcome=outcome,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl_percent=pnl_percent,
    )


def run_backtest(
    windows: list[tuple[Candle, Candle, Candle]],
    strategy: StrategyConfig,
) -> list[TradeResult]:
    """Run backtest on all windows."""
    results = []

    for c1, c2, c3 in windows:
        result = analyze_window(c1, c2, c3, strategy)
        results.append(result)

    return results


def print_results(results: list[TradeResult], strategy: StrategyConfig, bet_amount: float = 1.0):
    """Print backtest results summary."""

    total_windows = len(results)
    trades = [r for r in results if r.signal != "SKIP"]
    skips = [r for r in results if r.signal == "SKIP"]
    wins = [r for r in trades if r.outcome == "WIN"]
    losses = [r for r in trades if r.outcome == "LOSS"]

    up_trades = [r for r in trades if r.signal == "UP"]
    down_trades = [r for r in trades if r.signal == "DOWN"]

    up_wins = [r for r in up_trades if r.outcome == "WIN"]
    down_wins = [r for r in down_trades if r.outcome == "WIN"]

    print("\n" + "=" * 70)
    print("  BACKTEST RESULTS")
    print("=" * 70)
    print(f"\n  Strategy: {strategy.describe()}")

    if results:
        print(f"  Period: {results[0].window_start.strftime('%Y-%m-%d %H:%M')} to "
              f"{results[-1].window_start.strftime('%Y-%m-%d %H:%M')}")

    print(f"\n  Total 15-min windows analyzed: {total_windows}")
    print(f"  Trades taken: {len(trades)} ({len(trades)/total_windows*100:.1f}%)")
    print(f"  Skipped (mixed signals): {len(skips)} ({len(skips)/total_windows*100:.1f}%)")

    print("\n" + "-" * 70)
    print("  OVERALL PERFORMANCE")
    print("-" * 70)

    if trades:
        win_rate = len(wins) / len(trades) * 100
        print(f"\n  Wins: {len(wins)}")
        print(f"  Losses: {len(losses)}")
        print(f"  Win Rate: {win_rate:.1f}%")

        # Calculate P&L assuming 50/50 odds (simplification)
        # Win = +bet_amount, Loss = -bet_amount
        total_pnl = (len(wins) - len(losses)) * bet_amount
        print(f"\n  Simulated P&L (at $1/bet, 50% odds): ${total_pnl:+.2f}")

        # More realistic: assuming avg odds of 52% (slight edge)
        # Win pays: bet * (1/0.52 - 1) = bet * 0.923
        # Loss pays: -bet
        avg_win_payout = bet_amount * 0.923
        realistic_pnl = len(wins) * avg_win_payout - len(losses) * bet_amount
        print(f"  Simulated P&L (at $1/bet, 52% odds): ${realistic_pnl:+.2f}")

    print("\n" + "-" * 70)
    print("  BREAKDOWN BY SIGNAL TYPE")
    print("-" * 70)

    if up_trades:
        up_win_rate = len(up_wins) / len(up_trades) * 100
        print(f"\n  UP signals (GREEN+GREEN):")
        print(f"    Trades: {len(up_trades)}")
        print(f"    Wins: {len(up_wins)} | Losses: {len(up_trades) - len(up_wins)}")
        print(f"    Win Rate: {up_win_rate:.1f}%")

    if down_trades:
        down_win_rate = len(down_wins) / len(down_trades) * 100
        print(f"\n  DOWN signals (RED+RED):")
        print(f"    Trades: {len(down_trades)}")
        print(f"    Wins: {len(down_wins)} | Losses: {len(down_trades) - len(down_wins)}")
        print(f"    Win Rate: {down_win_rate:.1f}%")

    print("\n" + "-" * 70)
    print("  SIGNAL DISTRIBUTION")
    print("-" * 70)

    gg_count = sum(1 for r in results if r.candle_1_color == "GREEN" and r.candle_2_color == "GREEN")
    rr_count = sum(1 for r in results if r.candle_1_color == "RED" and r.candle_2_color == "RED")
    gr_count = sum(1 for r in results if r.candle_1_color == "GREEN" and r.candle_2_color == "RED")
    rg_count = sum(1 for r in results if r.candle_1_color == "RED" and r.candle_2_color == "GREEN")

    print(f"\n  GREEN + GREEN: {gg_count} ({gg_count/total_windows*100:.1f}%)")
    print(f"  RED + RED:     {rr_count} ({rr_count/total_windows*100:.1f}%)")
    print(f"  GREEN + RED:   {gr_count} ({gr_count/total_windows*100:.1f}%)")
    print(f"  RED + GREEN:   {rg_count} ({rg_count/total_windows*100:.1f}%)")

    print("\n" + "-" * 70)
    print("  HOURLY BREAKDOWN")
    print("-" * 70)

    # Group by hour
    hourly_stats = {}
    for r in trades:
        hour = r.window_start.hour
        if hour not in hourly_stats:
            hourly_stats[hour] = {"wins": 0, "losses": 0}
        if r.outcome == "WIN":
            hourly_stats[hour]["wins"] += 1
        else:
            hourly_stats[hour]["losses"] += 1

    print(f"\n  {'Hour':<6} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'Win Rate':<10}")
    print(f"  {'-'*6} {'-'*8} {'-'*6} {'-'*8} {'-'*10}")

    for hour in sorted(hourly_stats.keys()):
        stats = hourly_stats[hour]
        total = stats["wins"] + stats["losses"]
        wr = stats["wins"] / total * 100 if total > 0 else 0
        print(f"  {hour:02d}:00  {total:<8} {stats['wins']:<6} {stats['losses']:<8} {wr:.1f}%")

    print("\n" + "=" * 70)

    # Show recent trades
    print("\n  RECENT TRADES (last 20)")
    print("-" * 70)
    print(f"  {'Time':<18} {'C1':<6} {'C2':<6} {'Signal':<6} {'Actual':<6} {'Result':<6}")
    print(f"  {'-'*18} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")

    for r in results[-20:]:
        if r.signal != "SKIP":
            print(f"  {r.window_start.strftime('%Y-%m-%d %H:%M'):<18} "
                  f"{r.candle_1_color:<6} {r.candle_2_color:<6} "
                  f"{r.signal:<6} {r.candle_3_direction:<6} {r.outcome:<6}")

    print()


async def main():
    parser = argparse.ArgumentParser(
        description="Backtest the BTC trading strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Strategy Examples:
  Momentum (default):  --gg UP --rr DOWN --gr SKIP --rg SKIP
  Contrarian:          --gg DOWN --rr UP --gr SKIP --rg SKIP
  Always UP:           --gg UP --rr UP --gr SKIP --rg SKIP
  Always DOWN:         --gg DOWN --rr DOWN --gr SKIP --rg SKIP
  Bet on all:          --gg UP --rr DOWN --gr DOWN --rg UP

Preset strategies:
  --strategy momentum   (default)
  --strategy contrarian
        """,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to backtest (default: 7)",
    )
    parser.add_argument(
        "--bet-amount",
        type=float,
        default=1.0,
        help="Bet amount for P&L calculation (default: 1.0)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use generated sample data instead of fetching from Binance",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for sample data generation (default: 42)",
    )

    # Strategy arguments
    parser.add_argument(
        "--strategy",
        choices=["momentum", "contrarian"],
        help="Use a preset strategy (overrides individual --gg, --rr, etc.)",
    )
    parser.add_argument(
        "--gg",
        choices=["UP", "DOWN", "SKIP"],
        default="UP",
        help="Action for GREEN+GREEN pattern (default: UP)",
    )
    parser.add_argument(
        "--rr",
        choices=["UP", "DOWN", "SKIP"],
        default="DOWN",
        help="Action for RED+RED pattern (default: DOWN)",
    )
    parser.add_argument(
        "--gr",
        choices=["UP", "DOWN", "SKIP"],
        default="SKIP",
        help="Action for GREEN+RED pattern (default: SKIP)",
    )
    parser.add_argument(
        "--rg",
        choices=["UP", "DOWN", "SKIP"],
        default="SKIP",
        help="Action for RED+GREEN pattern (default: SKIP)",
    )

    args = parser.parse_args()

    # Build strategy config
    if args.strategy == "momentum":
        strategy = StrategyConfig.momentum()
    elif args.strategy == "contrarian":
        strategy = StrategyConfig.contrarian()
    else:
        strategy = StrategyConfig.from_args(
            gg=args.gg,
            rr=args.rr,
            gr=args.gr,
            rg=args.rg,
        )

    # Fetch historical data
    if args.offline:
        print(f"Generating {args.days} days of sample candle data (seed={args.seed})...")
        candles = generate_sample_candles(days=args.days, seed=args.seed)
    else:
        try:
            candles = await fetch_historical_candles(days=args.days, offline=False)
        except Exception as e:
            print(f"Failed to fetch from Binance: {e}")
            print("Falling back to offline mode with sample data...")
            candles = generate_sample_candles(days=args.days, seed=args.seed)

    if not candles:
        print("Error: No candles fetched")
        return

    # Group into 15-minute windows
    windows = group_into_windows(candles)
    print(f"\nGrouped into {len(windows)} complete 15-minute windows")

    if not windows:
        print("Error: No complete windows found")
        return

    # Run backtest
    results = run_backtest(windows, strategy)

    # Print results
    print_results(results, strategy, bet_amount=args.bet_amount)


if __name__ == "__main__":
    asyncio.run(main())

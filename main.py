#!/usr/bin/env python3
"""
Polymarket BTC 15-Minute Trading Bot

A simple bot that bets on BTC price direction based on candlestick patterns.

Strategy:
- Two green candles → Bet UP (BTC will go up)
- Two red candles → Bet DOWN (BTC will go down)
- Mixed candles → Skip

Usage:
    python main.py              # Run the bot
    python main.py --once       # Run once and exit
    python main.py --status     # Show current status and stats
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

import structlog


def setup_logging(level: str = "INFO"):
    """Configure structured logging."""
    import logging

    # Set up standard logging first
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )

    # Configure structlog to use standard library
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Polymarket BTC 15-Minute Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (don't loop)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status and statistics",
    )
    parser.add_argument(
        "--test-candles",
        action="store_true",
        help="Test candle fetching from Binance",
    )
    parser.add_argument(
        "--test-market",
        action="store_true",
        help="Test finding Polymarket BTC markets",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()

    # Setup logging
    from src.config import settings
    setup_logging(args.log_level or settings.log_level)

    # Handle different modes
    if args.status:
        from src.tracker import BetTracker
        tracker = BetTracker()
        tracker.print_summary()
        return

    if args.test_candles:
        from src.price_fetcher import BinancePriceFetcher

        print("\nTesting Binance candle fetching...")
        fetcher = BinancePriceFetcher()
        try:
            candles = await fetcher.get_recent_candles(5)
            print("\nRecent 5-minute candles:")
            for candle in candles:
                status = "CLOSED" if candle.is_closed else "OPEN  "
                print(f"  [{status}] {candle}")

            print("\nLast two closed candles:")
            c1, c2 = await fetcher.get_last_two_closed_candles()
            print(f"  {c1}")
            print(f"  {c2}")

            from src.candle_analyzer import analyze_candles
            signal = analyze_candles(c1, c2)
            print(f"\nSignal: {signal}")
        finally:
            await fetcher.close()
        return

    if args.test_market:
        from src.polymarket_client import PolymarketClient

        print("\nSearching for BTC 15-minute markets on Polymarket...")
        client = PolymarketClient()
        try:
            market = await client.find_btc_15min_market()
            if market:
                print(f"\nFound market:")
                print(f"  Question: {market.question}")
                print(f"  Condition ID: {market.condition_id}")
                print(f"  End date: {market.end_date}")
                print(f"  Yes price: {market.outcome_prices.get('Yes', 'N/A')}")
                print(f"  No price: {market.outcome_prices.get('No', 'N/A')}")
            else:
                print("\nNo active BTC 15-minute market found")
                print("This could mean:")
                print("  - No markets are currently active")
                print("  - Market naming doesn't match expected patterns")
        finally:
            await client.close()
        return

    # Run the bot
    from src.bot import PolymarketBTCBot

    bot = PolymarketBTCBot()

    if args.once:
        print("\nRunning single iteration...")
        await bot.run_once()
        await bot.stop()
    else:
        await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")

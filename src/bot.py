"""Main bot logic for the Polymarket BTC trading bot."""

import asyncio
from datetime import datetime, timedelta
import structlog

from .config import settings
from .price_fetcher import BinancePriceFetcher
from .candle_analyzer import analyze_candles, get_signal_for_polymarket, Signal
from .polymarket_client import PolymarketClient
from .tracker import BetTracker

logger = structlog.get_logger()


def get_current_15min_window(now: datetime = None) -> tuple[datetime, datetime]:
    """
    Get the start and end times of the current 15-minute window.

    Windows are: :00-:15, :15-:30, :30-:45, :45-:00

    Returns:
        Tuple of (window_start, window_end)
    """
    if now is None:
        now = datetime.now()

    # Find the start of the current 15-minute window
    minute = now.minute
    window_start_minute = (minute // 15) * 15

    window_start = now.replace(minute=window_start_minute, second=0, microsecond=0)
    window_end = window_start + timedelta(minutes=15)

    return window_start, window_end


def get_bet_time(window_start: datetime) -> datetime:
    """
    Get the time when we should place our bet for this window.

    We bet at minute 10 of each 15-minute window (after two 5-min candles close).
    """
    return window_start + timedelta(minutes=10)


def seconds_until(target: datetime, now: datetime = None) -> float:
    """Get seconds until target time."""
    if now is None:
        now = datetime.now()
    return (target - now).total_seconds()


class PolymarketBTCBot:
    """Main bot class that coordinates all components."""

    def __init__(self):
        self.price_fetcher = BinancePriceFetcher()
        self.polymarket_client = PolymarketClient()
        self.tracker = BetTracker()
        self.running = False
        self._last_bet_window: datetime | None = None

    async def start(self):
        """Start the bot."""
        self.running = True

        # Print startup banner
        now = datetime.now()
        window_start, window_end = get_current_15min_window(now)
        bet_time = get_bet_time(window_start)

        # If we're past bet time for this window, show next window
        if now >= bet_time:
            next_window_start = window_end
            next_bet_time = get_bet_time(next_window_start)
        else:
            next_bet_time = bet_time

        print("\n" + "=" * 60)
        print("  POLYMARKET BTC 15-MINUTE BOT")
        print("=" * 60)
        print(f"  Mode: {settings.get_mode_description()}")
        print(f"  Strategy: {settings.get_strategy_description()}")
        print(f"  Bet Amount: ${settings.bet_amount:.2f}")
        print(f"  Min Odds: {settings.min_odds:.0%} | Max Odds: {settings.max_odds:.0%}")
        print("=" * 60)
        print("\n  Timing: Bet at :10, :25, :40, :55 of each hour")
        print("  (After two 5-min candles close within each 15-min window)")
        print(f"\n  Current time: {now.strftime('%H:%M:%S')}")
        print(f"  Next bet at: {next_bet_time.strftime('%H:%M:%S')} ({seconds_until(next_bet_time, now):.0f}s)\n")

        if not settings.is_trading_enabled():
            logger.warning(
                "running_in_monitoring_mode",
                reason="Wallet credentials not configured",
            )
            print("*** MONITORING MODE: No real bets will be placed ***")
            print("*** Configure WALLET_ADDRESS and PRIVATE_KEY for live trading ***\n")

        # Print current stats
        self.tracker.print_summary()

        logger.info("bot_started", mode=settings.get_mode_description())

        try:
            await self._run_loop()
        except KeyboardInterrupt:
            logger.info("bot_stopped_by_user")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the bot and cleanup resources."""
        self.running = False
        await self.price_fetcher.close()
        await self.polymarket_client.close()
        logger.info("bot_stopped")

    async def _run_loop(self):
        """
        Main bot loop aligned with 15-minute windows.

        Timing:
        - 15-min windows: :00-:15, :15-:30, :30-:45, :45-:00
        - Bet placement: :10, :25, :40, :55 (10 mins into each window)
        - Market resolves: :15, :30, :45, :00 (5 mins after bet)
        """
        while self.running:
            try:
                now = datetime.now()
                window_start, window_end = get_current_15min_window(now)
                bet_time = get_bet_time(window_start)

                # Check if we already bet on this window
                if self._last_bet_window == window_start:
                    # Wait for next window
                    wait_seconds = seconds_until(window_end, now) + 1
                    print(f"\n[{now.strftime('%H:%M:%S')}] Already bet on this window. "
                          f"Next window starts at {window_end.strftime('%H:%M:%S')} "
                          f"(waiting {wait_seconds:.0f}s)")
                    await asyncio.sleep(min(wait_seconds, 60))
                    continue

                # Check if it's time to bet
                if now < bet_time:
                    # Wait until bet time
                    wait_seconds = seconds_until(bet_time, now)
                    print(f"\n[{now.strftime('%H:%M:%S')}] Window: {window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')} | "
                          f"Bet time: {bet_time.strftime('%H:%M:%S')} | "
                          f"Waiting {wait_seconds:.0f}s...")

                    # Sleep in chunks to allow for graceful shutdown
                    while wait_seconds > 0 and self.running:
                        sleep_time = min(wait_seconds, 10)
                        await asyncio.sleep(sleep_time)
                        wait_seconds -= sleep_time
                    continue

                # It's bet time! Execute the trade
                print(f"\n{'='*60}")
                print(f"[{now.strftime('%H:%M:%S')}] BET TIME for window {window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')}")
                print(f"{'='*60}")

                await self._execute_trade(window_start, window_end)
                self._last_bet_window = window_start

                # Wait a bit before checking for next window
                await asyncio.sleep(5)

            except Exception as e:
                logger.error("error_in_main_loop", error=str(e))
                await asyncio.sleep(10)

    async def _execute_trade(self, window_start: datetime, window_end: datetime):
        """
        Execute trade for the current 15-minute window.

        Args:
            window_start: Start of the 15-minute window
            window_end: End of the 15-minute window (market resolution time)
        """
        # Check if it's too early - candles need 10 minutes to form
        now = datetime.now()
        bet_time = get_bet_time(window_start)

        if now < bet_time:
            wait_seconds = seconds_until(bet_time, now)
            logger.warning(
                "too_early_for_candles",
                window_start=window_start.isoformat(),
                bet_time=bet_time.isoformat(),
                wait_seconds=wait_seconds,
            )
            print(f"\n  Too early! Candles not yet closed.")
            print(f"  Need to wait until {bet_time.strftime('%H:%M:%S')} ({wait_seconds:.0f}s)")
            return

        # Step 1: Get the two 5-minute candles from this window
        # Candle 1: window_start to window_start + 5min
        # Candle 2: window_start + 5min to window_start + 10min
        try:
            candle_1, candle_2 = await self.price_fetcher.get_candles_for_window(window_start)
        except ValueError as e:
            # Candles not ready yet - this can happen at edge of bet time
            logger.warning("candles_not_ready", error=str(e))
            print(f"  Candles not ready yet: {e}")
            print(f"  Will retry on next cycle...")
            return
        except Exception as e:
            logger.error("failed_to_get_candles", error=str(e))
            print(f"  ERROR: Failed to get candles - {e}")
            return

        # Step 2: Analyze candles for signal
        signal_result = analyze_candles(candle_1, candle_2)

        # Log current state
        print(f"\n  Candle Analysis:")
        print(f"    Candle 1 ({window_start.strftime('%H:%M')}-{(window_start + timedelta(minutes=5)).strftime('%H:%M')}): {candle_1.color} | O:{candle_1.open_price:.2f} C:{candle_1.close_price:.2f}")
        print(f"    Candle 2 ({(window_start + timedelta(minutes=5)).strftime('%H:%M')}-{(window_start + timedelta(minutes=10)).strftime('%H:%M')}): {candle_2.color} | O:{candle_2.open_price:.2f} C:{candle_2.close_price:.2f}")
        print(f"    Signal: {signal_result.signal.value} - {signal_result.reason}")

        # Step 3: Check if we should skip
        if signal_result.signal == Signal.SKIP:
            self.tracker.record_skip(
                signal=signal_result.signal,
                candle_1_color=candle_1.color,
                candle_2_color=candle_2.color,
                reason=signal_result.reason,
            )
            print(f"\n  Action: SKIP - {signal_result.reason}")
            return

        # Step 4: Find the BTC 15-minute market ending at window_end
        market = await self.polymarket_client.find_btc_15min_market()

        if not market:
            logger.warning("no_market_found", signal=signal_result.signal.value)
            print(f"\n  Action: SKIP - No active BTC 15-minute market found")

            # Still record what we would have bet
            print(f"  Would have bet: {signal_result.signal.value}")
            return

        # Step 5: Check odds
        side = get_signal_for_polymarket(signal_result.signal)
        if side is None:
            return

        price = market.outcome_prices.get(side, 0.5)

        print(f"\n  Market: {market.question[:70]}...")
        print(f"  Market ends: {market.end_date.strftime('%H:%M:%S') if market.end_date else 'Unknown'}")
        print(f"  Current odds: Yes={market.outcome_prices.get('Yes', 0):.2%} | No={market.outcome_prices.get('No', 0):.2%}")

        if price < settings.min_odds:
            logger.debug("odds_too_low", price=price, min=settings.min_odds)
            print(f"\n  Action: SKIP - Odds too low ({price:.2%} < {settings.min_odds:.0%})")
            return

        if price > settings.max_odds:
            logger.debug("odds_too_high", price=price, max=settings.max_odds)
            print(f"\n  Action: SKIP - Odds too high ({price:.2%} > {settings.max_odds:.0%})")
            return

        # Step 6: Place the bet
        print(f"\n  Placing bet: {side} @ {price:.2%} for ${settings.bet_amount:.2f}")

        bet_result = await self.polymarket_client.place_bet(
            market=market,
            side=side,
            amount=settings.bet_amount,
        )

        if bet_result.success:
            # Record the bet
            self.tracker.record_bet(
                signal=signal_result.signal,
                market=market,
                bet_result=bet_result,
                candle_1_color=candle_1.color,
                candle_2_color=candle_2.color,
            )

            mode = "SIMULATED" if bet_result.simulated else "LIVE"
            print(f"\n  Result: {mode} BET PLACED")
            print(f"    Side: {bet_result.side}")
            print(f"    Price: {bet_result.price:.2%}")
            print(f"    Amount: ${bet_result.amount:.2f}")
            print(f"    Market resolves at: {window_end.strftime('%H:%M:%S')}")
        else:
            logger.error("bet_failed", error=bet_result.error)
            print(f"\n  Result: BET FAILED - {bet_result.error}")

    async def run_once(self, wait_for_bet_time: bool = True):
        """
        Run a single iteration for the current window (useful for testing).

        Args:
            wait_for_bet_time: If True, wait until bet time if started early.
                              If False, will return early if candles not ready.
        """
        now = datetime.now()
        window_start, window_end = get_current_15min_window(now)
        bet_time = get_bet_time(window_start)

        print(f"\n[{now.strftime('%H:%M:%S')}] Running single iteration")
        print(f"  Current window: {window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')}")
        print(f"  Bet time: {bet_time.strftime('%H:%M:%S')}")

        # Check if we need to wait
        if now < bet_time:
            wait_seconds = seconds_until(bet_time, now)
            if wait_for_bet_time:
                print(f"  Waiting {wait_seconds:.0f}s for candles to close...")
                await asyncio.sleep(wait_seconds + 1)  # +1 second buffer
            else:
                print(f"  Too early - candles close in {wait_seconds:.0f}s")
                await self.stop()
                return

        await self._execute_trade(window_start, window_end)
        await self.stop()


async def run_bot():
    """Entry point to run the bot."""
    bot = PolymarketBTCBot()
    await bot.start()


if __name__ == "__main__":
    asyncio.run(run_bot())

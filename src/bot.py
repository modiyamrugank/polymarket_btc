"""Main bot logic for the Polymarket BTC trading bot."""

import asyncio
from datetime import datetime
import structlog

from .config import settings
from .price_fetcher import BinancePriceFetcher
from .candle_analyzer import analyze_candles, get_signal_for_polymarket, Signal
from .polymarket_client import PolymarketClient
from .tracker import BetTracker

logger = structlog.get_logger()

# How often to check for new candle data (in seconds)
CHECK_INTERVAL = 60  # Check every minute

# Time buffer before market end to place bets (in seconds)
BET_BUFFER_SECONDS = 120  # Place bet at least 2 minutes before market ends


class PolymarketBTCBot:
    """Main bot class that coordinates all components."""

    def __init__(self):
        self.price_fetcher = BinancePriceFetcher()
        self.polymarket_client = PolymarketClient()
        self.tracker = BetTracker()
        self.running = False
        self._last_bet_market_id: str | None = None

    async def start(self):
        """Start the bot."""
        self.running = True

        # Print startup banner
        print("\n" + "=" * 60)
        print("  POLYMARKET BTC 15-MINUTE BOT")
        print("=" * 60)
        print(f"  Mode: {settings.get_mode_description()}")
        print(f"  Bet Amount: ${settings.bet_amount:.2f}")
        print(f"  Min Odds: {settings.min_odds:.0%} | Max Odds: {settings.max_odds:.0%}")
        print("=" * 60 + "\n")

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
        """Main bot loop."""
        while self.running:
            try:
                await self._check_and_trade()
            except Exception as e:
                logger.error("error_in_main_loop", error=str(e))

            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL)

    async def _check_and_trade(self):
        """Check market conditions and place trade if appropriate."""
        logger.debug("checking_market_conditions")

        # Step 1: Get the last two closed candles
        try:
            candle_1, candle_2 = await self.price_fetcher.get_last_two_closed_candles()
        except Exception as e:
            logger.error("failed_to_get_candles", error=str(e))
            return

        # Step 2: Analyze candles for signal
        signal_result = analyze_candles(candle_1, candle_2)

        # Log current state
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Candle Analysis:")
        print(f"  Candle 1: {candle_1}")
        print(f"  Candle 2: {candle_2}")
        print(f"  Signal: {signal_result}")

        # Step 3: Check if we should skip
        if signal_result.signal == Signal.SKIP:
            self.tracker.record_skip(
                signal=signal_result.signal,
                candle_1_color=candle_1.color,
                candle_2_color=candle_2.color,
                reason=signal_result.reason,
            )
            print(f"  Action: SKIP - {signal_result.reason}")
            return

        # Step 4: Find an active BTC 15-minute market
        market = await self.polymarket_client.find_btc_15min_market()

        if not market:
            logger.warning("no_market_found", signal=signal_result.signal.value)
            print("  Action: SKIP - No active BTC 15-minute market found")
            return

        # Check if we already bet on this market
        if market.condition_id == self._last_bet_market_id:
            logger.debug("already_bet_on_market", market_id=market.condition_id)
            print(f"  Action: SKIP - Already bet on this market")
            return

        # Step 5: Check market timing
        now = datetime.now(market.end_date.tzinfo) if market.end_date.tzinfo else datetime.now()
        time_to_end = (market.end_date - now).total_seconds()

        if time_to_end < BET_BUFFER_SECONDS:
            logger.debug("market_ending_soon", seconds_remaining=time_to_end)
            print(f"  Action: SKIP - Market ends in {time_to_end:.0f}s (need {BET_BUFFER_SECONDS}s buffer)")
            return

        # Step 6: Check odds
        side = get_signal_for_polymarket(signal_result.signal)
        if side is None:
            return

        price = market.outcome_prices.get(side, 0.5)

        if price < settings.min_odds:
            logger.debug("odds_too_low", price=price, min=settings.min_odds)
            print(f"  Action: SKIP - Odds too low ({price:.2%} < {settings.min_odds:.0%})")
            return

        if price > settings.max_odds:
            logger.debug("odds_too_high", price=price, max=settings.max_odds)
            print(f"  Action: SKIP - Odds too high ({price:.2%} > {settings.max_odds:.0%})")
            return

        # Step 7: Place the bet
        print(f"\n  Market: {market.question[:60]}...")
        print(f"  Placing bet: {side} @ {price:.2%} for ${settings.bet_amount:.2f}")

        bet_result = await self.polymarket_client.place_bet(
            market=market,
            side=side,
            amount=settings.bet_amount,
        )

        if bet_result.success:
            self._last_bet_market_id = market.condition_id

            # Record the bet
            self.tracker.record_bet(
                signal=signal_result.signal,
                market=market,
                bet_result=bet_result,
                candle_1_color=candle_1.color,
                candle_2_color=candle_2.color,
            )

            mode = "SIMULATED" if bet_result.simulated else "LIVE"
            print(f"  Result: {mode} BET PLACED - {bet_result}")
        else:
            logger.error("bet_failed", error=bet_result.error)
            print(f"  Result: BET FAILED - {bet_result.error}")

    async def run_once(self):
        """Run a single iteration (useful for testing)."""
        await self._check_and_trade()


async def run_bot():
    """Entry point to run the bot."""
    bot = PolymarketBTCBot()
    await bot.start()


if __name__ == "__main__":
    asyncio.run(run_bot())

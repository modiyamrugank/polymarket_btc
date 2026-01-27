"""BTC price data fetcher using Binance API."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import aiohttp
import structlog

logger = structlog.get_logger()

# Binance API endpoints (no auth required for public market data)
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_5m"


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
    is_closed: bool

    @property
    def is_green(self) -> bool:
        """Returns True if candle closed higher than it opened."""
        return self.close_price > self.open_price

    @property
    def is_red(self) -> bool:
        """Returns True if candle closed lower than it opened."""
        return self.close_price < self.open_price

    @property
    def color(self) -> str:
        """Returns the candle color as a string."""
        if self.is_green:
            return "GREEN"
        elif self.is_red:
            return "RED"
        return "DOJI"  # Open == Close

    def __str__(self) -> str:
        return (
            f"Candle({self.open_time.strftime('%H:%M')} - {self.close_time.strftime('%H:%M')}: "
            f"O={self.open_price:.2f}, H={self.high_price:.2f}, L={self.low_price:.2f}, "
            f"C={self.close_price:.2f}, {self.color})"
        )


class BinancePriceFetcher:
    """Fetches BTC price data from Binance."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_recent_candles(self, limit: int = 3) -> list[Candle]:
        """
        Fetch the most recent 5-minute candles for BTC/USDT.

        Args:
            limit: Number of candles to fetch (default 3 to ensure we have 2 closed)

        Returns:
            List of Candle objects, ordered oldest to newest
        """
        session = await self._get_session()

        params = {
            "symbol": "BTCUSDT",
            "interval": "5m",
            "limit": limit,
        }

        try:
            async with session.get(BINANCE_KLINES_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json()

                candles = []
                for kline in data:
                    # Binance kline format:
                    # [open_time, open, high, low, close, volume, close_time, ...]
                    open_time = datetime.fromtimestamp(kline[0] / 1000)
                    close_time = datetime.fromtimestamp(kline[6] / 1000)

                    # A candle is closed if its close time has passed
                    is_closed = datetime.now() > close_time

                    candle = Candle(
                        open_time=open_time,
                        open_price=float(kline[1]),
                        high_price=float(kline[2]),
                        low_price=float(kline[3]),
                        close_price=float(kline[4]),
                        close_time=close_time,
                        volume=float(kline[5]),
                        is_closed=is_closed,
                    )
                    candles.append(candle)

                logger.debug("fetched_candles", count=len(candles))
                return candles

        except aiohttp.ClientError as e:
            logger.error("failed_to_fetch_candles", error=str(e))
            raise

    async def get_last_two_closed_candles(self) -> tuple[Candle, Candle]:
        """
        Get the last two fully closed 5-minute candles.

        Returns:
            Tuple of (second_to_last_candle, last_candle)
        """
        candles = await self.get_recent_candles(limit=5)

        # Filter to only closed candles
        closed_candles = [c for c in candles if c.is_closed]

        if len(closed_candles) < 2:
            raise ValueError(f"Not enough closed candles. Got {len(closed_candles)}, need 2.")

        # Return the last two closed candles
        return closed_candles[-2], closed_candles[-1]

    async def get_candles_for_window(self, window_start: datetime) -> tuple[Candle, Candle]:
        """
        Get the two 5-minute candles that fall within a 15-minute window.

        For a window starting at :00, this returns:
        - Candle 1: :00 - :05
        - Candle 2: :05 - :10

        Args:
            window_start: The start time of the 15-minute window

        Returns:
            Tuple of (candle_1, candle_2) - the two 5-minute candles
        """
        session = await self._get_session()

        # Calculate the expected candle times
        candle_1_open = window_start
        candle_1_close = window_start + timedelta(minutes=5)
        candle_2_open = candle_1_close
        candle_2_close = window_start + timedelta(minutes=10)

        # Fetch candles with specific start and end times
        # We use startTime and endTime to get exactly the candles we need
        params = {
            "symbol": "BTCUSDT",
            "interval": "5m",
            "startTime": int(candle_1_open.timestamp() * 1000),
            "endTime": int(candle_2_close.timestamp() * 1000),
            "limit": 3,  # Should get exactly 2-3 candles
        }

        try:
            async with session.get(BINANCE_KLINES_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json()

                if len(data) < 2:
                    raise ValueError(
                        f"Not enough candles for window starting at {window_start}. "
                        f"Got {len(data)}, need 2."
                    )

                candles = []
                for kline in data[:2]:  # Take first two candles
                    open_time = datetime.fromtimestamp(kline[0] / 1000)
                    close_time = datetime.fromtimestamp(kline[6] / 1000)

                    # A candle is closed if its close time has passed
                    is_closed = datetime.now() > close_time

                    candle = Candle(
                        open_time=open_time,
                        open_price=float(kline[1]),
                        high_price=float(kline[2]),
                        low_price=float(kline[3]),
                        close_price=float(kline[4]),
                        close_time=close_time,
                        volume=float(kline[5]),
                        is_closed=is_closed,
                    )
                    candles.append(candle)

                # Verify we got the correct candles
                candle_1, candle_2 = candles[0], candles[1]

                if not candle_1.is_closed or not candle_2.is_closed:
                    raise ValueError(
                        f"Candles not yet closed. Candle 1 closed: {candle_1.is_closed}, "
                        f"Candle 2 closed: {candle_2.is_closed}"
                    )

                logger.debug(
                    "fetched_window_candles",
                    window_start=window_start.isoformat(),
                    candle_1_time=candle_1.open_time.isoformat(),
                    candle_2_time=candle_2.open_time.isoformat(),
                )

                return candle_1, candle_2

        except aiohttp.ClientError as e:
            logger.error("failed_to_fetch_window_candles", error=str(e))
            raise


# Global fetcher instance
price_fetcher = BinancePriceFetcher()


async def main():
    """Test the price fetcher."""
    fetcher = BinancePriceFetcher()
    try:
        candles = await fetcher.get_recent_candles(5)
        print("Recent candles:")
        for candle in candles:
            status = "CLOSED" if candle.is_closed else "OPEN"
            print(f"  [{status}] {candle}")

        print("\nLast two closed candles:")
        c1, c2 = await fetcher.get_last_two_closed_candles()
        print(f"  {c1}")
        print(f"  {c2}")
    finally:
        await fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())

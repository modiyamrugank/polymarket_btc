"""Polymarket API client for BTC 15-minute markets."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import aiohttp
import structlog

from .config import settings

logger = structlog.get_logger()

# Polymarket API endpoints
POLYMARKET_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"


@dataclass
class Market:
    """Represents a Polymarket market."""

    condition_id: str
    question: str
    description: str
    end_date: datetime
    tokens: list[dict]  # Yes/No token info
    outcome_prices: dict[str, float]  # Current prices for Yes/No
    min_tick_size: float
    active: bool

    def __str__(self) -> str:
        yes_price = self.outcome_prices.get("Yes", 0)
        no_price = self.outcome_prices.get("No", 0)
        return f"Market: {self.question[:50]}... | Yes: {yes_price:.2f} | No: {no_price:.2f}"


@dataclass
class BetResult:
    """Result of a bet attempt."""

    success: bool
    market: Market
    side: str  # "Yes" or "No"
    amount: float
    price: float
    order_id: Optional[str] = None
    error: Optional[str] = None
    simulated: bool = False

    def __str__(self) -> str:
        status = "SIMULATED" if self.simulated else ("SUCCESS" if self.success else "FAILED")
        return f"Bet {status}: {self.side} @ {self.price:.2f} for ${self.amount:.2f}"


class PolymarketClient:
    """Client for interacting with Polymarket API."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._clob_client = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _init_clob_client(self):
        """Initialize the CLOB client for trading (requires credentials)."""
        if self._clob_client is not None:
            return self._clob_client

        if not settings.is_trading_enabled():
            logger.warning("trading_disabled", reason="Missing wallet credentials")
            return None

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            # Initialize with Polygon mainnet
            host = POLYMARKET_API_URL
            chain_id = 137  # Polygon mainnet

            # Create API credentials if available
            creds = None
            if settings.polymarket_api_key:
                creds = ApiCreds(
                    api_key=settings.polymarket_api_key,
                    api_secret=settings.polymarket_api_secret or "",
                    api_passphrase=settings.polymarket_passphrase or "",
                )

            self._clob_client = ClobClient(
                host=host,
                chain_id=chain_id,
                key=settings.private_key,
                creds=creds,
            )

            logger.info("clob_client_initialized")
            return self._clob_client

        except Exception as e:
            logger.error("failed_to_init_clob_client", error=str(e))
            return None

    async def find_btc_15min_market(self) -> Optional[Market]:
        """
        Find the current active BTC 15-minute up/down market.

        These markets are typically named like:
        - "Will BTC be above $X at HH:MM UTC?"
        - "Bitcoin 15 Minute Up or Down"
        """
        session = await self._get_session()

        try:
            # Search for BTC-related markets
            params = {
                "active": "true",
                "closed": "false",
                "limit": 100,
            }

            async with session.get(f"{GAMMA_API_URL}/markets", params=params) as response:
                response.raise_for_status()
                markets = await response.json()

                # Filter for BTC 15-minute markets
                btc_markets = []
                for market in markets:
                    question = market.get("question", "").lower()
                    description = market.get("description", "").lower()

                    # Look for BTC/Bitcoin 15-minute markets
                    is_btc = "btc" in question or "bitcoin" in question
                    is_15min = (
                        "15 min" in question
                        or "15min" in question
                        or "fifteen min" in question
                        or "15 min" in description
                    )

                    if is_btc and is_15min:
                        btc_markets.append(market)

                if not btc_markets:
                    # Try alternative search - look for any short-term BTC price markets
                    for market in markets:
                        question = market.get("question", "").lower()
                        is_btc = "btc" in question or "bitcoin" in question
                        is_price = "price" in question or "above" in question or "below" in question

                        # Check if it expires soon (within 30 minutes)
                        end_date_str = market.get("endDate")
                        if end_date_str and is_btc and is_price:
                            try:
                                end_date = datetime.fromisoformat(
                                    end_date_str.replace("Z", "+00:00")
                                )
                                now = datetime.now(end_date.tzinfo)
                                minutes_to_end = (end_date - now).total_seconds() / 60

                                if 0 < minutes_to_end <= 30:
                                    btc_markets.append(market)
                            except (ValueError, TypeError):
                                pass

                if not btc_markets:
                    logger.warning("no_btc_15min_market_found")
                    return None

                # Get the market expiring soonest
                best_market = None
                soonest_end = None

                for market in btc_markets:
                    end_date_str = market.get("endDate")
                    if end_date_str:
                        try:
                            end_date = datetime.fromisoformat(
                                end_date_str.replace("Z", "+00:00")
                            )
                            if soonest_end is None or end_date < soonest_end:
                                soonest_end = end_date
                                best_market = market
                        except (ValueError, TypeError):
                            pass

                if not best_market:
                    best_market = btc_markets[0]

                # Parse market data
                tokens = best_market.get("tokens", [])
                outcome_prices = {}
                for token in tokens:
                    outcome = token.get("outcome", "")
                    price = float(token.get("price", 0))
                    outcome_prices[outcome] = price

                end_date_str = best_market.get("endDate", "")
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    end_date = datetime.now()

                return Market(
                    condition_id=best_market.get("conditionId", ""),
                    question=best_market.get("question", ""),
                    description=best_market.get("description", ""),
                    end_date=end_date,
                    tokens=tokens,
                    outcome_prices=outcome_prices,
                    min_tick_size=float(best_market.get("minTickSize", 0.01)),
                    active=best_market.get("active", False),
                )

        except aiohttp.ClientError as e:
            logger.error("failed_to_fetch_markets", error=str(e))
            return None

    async def get_market_by_condition_id(self, condition_id: str) -> Optional[Market]:
        """Fetch a specific market by its condition ID."""
        session = await self._get_session()

        try:
            async with session.get(f"{GAMMA_API_URL}/markets/{condition_id}") as response:
                if response.status == 404:
                    return None

                response.raise_for_status()
                market = await response.json()

                tokens = market.get("tokens", [])
                outcome_prices = {}
                for token in tokens:
                    outcome = token.get("outcome", "")
                    price = float(token.get("price", 0))
                    outcome_prices[outcome] = price

                end_date_str = market.get("endDate", "")
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    end_date = datetime.now()

                return Market(
                    condition_id=market.get("conditionId", ""),
                    question=market.get("question", ""),
                    description=market.get("description", ""),
                    end_date=end_date,
                    tokens=tokens,
                    outcome_prices=outcome_prices,
                    min_tick_size=float(market.get("minTickSize", 0.01)),
                    active=market.get("active", False),
                )

        except aiohttp.ClientError as e:
            logger.error("failed_to_fetch_market", condition_id=condition_id, error=str(e))
            return None

    async def place_bet(
        self,
        market: Market,
        side: str,  # "Yes" or "No"
        amount: float,
    ) -> BetResult:
        """
        Place a bet on a market.

        Args:
            market: The market to bet on
            side: "Yes" or "No"
            amount: Amount in USDC to bet

        Returns:
            BetResult with success status and details
        """
        price = market.outcome_prices.get(side, 0.5)

        # Check if we're in simulation mode
        if settings.dry_run or not settings.is_trading_enabled():
            logger.info(
                "simulated_bet",
                market=market.question[:50],
                side=side,
                amount=amount,
                price=price,
            )
            return BetResult(
                success=True,
                market=market,
                side=side,
                amount=amount,
                price=price,
                simulated=True,
            )

        # Attempt real trade
        client = self._init_clob_client()
        if client is None:
            return BetResult(
                success=False,
                market=market,
                side=side,
                amount=amount,
                price=price,
                error="CLOB client not initialized",
            )

        try:
            from py_clob_client.clob_types import OrderArgs
            from py_clob_client.order_builder.constants import BUY

            # Find the token ID for the side we want to bet on
            token_id = None
            for token in market.tokens:
                if token.get("outcome") == side:
                    token_id = token.get("token_id")
                    break

            if not token_id:
                return BetResult(
                    success=False,
                    market=market,
                    side=side,
                    amount=amount,
                    price=price,
                    error=f"Token ID not found for outcome: {side}",
                )

            # Create and submit order
            order_args = OrderArgs(
                price=price,
                size=amount / price,  # Convert USDC amount to shares
                side=BUY,
                token_id=token_id,
            )

            signed_order = client.create_order(order_args)
            response = client.post_order(signed_order)

            order_id = response.get("orderID")
            logger.info(
                "bet_placed",
                order_id=order_id,
                market=market.question[:50],
                side=side,
                amount=amount,
                price=price,
            )

            return BetResult(
                success=True,
                market=market,
                side=side,
                amount=amount,
                price=price,
                order_id=order_id,
            )

        except Exception as e:
            logger.error("failed_to_place_bet", error=str(e))
            return BetResult(
                success=False,
                market=market,
                side=side,
                amount=amount,
                price=price,
                error=str(e),
            )


# Global client instance
polymarket_client = PolymarketClient()


async def main():
    """Test the Polymarket client."""
    client = PolymarketClient()
    try:
        print("Searching for BTC 15-minute markets...")
        market = await client.find_btc_15min_market()
        if market:
            print(f"\nFound market:")
            print(f"  Question: {market.question}")
            print(f"  End date: {market.end_date}")
            print(f"  Yes price: {market.outcome_prices.get('Yes', 'N/A')}")
            print(f"  No price: {market.outcome_prices.get('No', 'N/A')}")
        else:
            print("No BTC 15-minute market found")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

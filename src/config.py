"""Configuration management for the Polymarket BTC bot."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Bot configuration settings loaded from environment variables."""

    # Wallet Configuration
    wallet_address: Optional[str] = Field(default=None, alias="WALLET_ADDRESS")
    private_key: Optional[str] = Field(default=None, alias="PRIVATE_KEY")

    # Polymarket API Configuration
    polymarket_api_key: Optional[str] = Field(default=None, alias="POLYMARKET_API_KEY")
    polymarket_api_secret: Optional[str] = Field(default=None, alias="POLYMARKET_API_SECRET")
    polymarket_passphrase: Optional[str] = Field(default=None, alias="POLYMARKET_PASSPHRASE")

    # Binance API Configuration
    binance_api_key: Optional[str] = Field(default=None, alias="BINANCE_API_KEY")
    binance_api_secret: Optional[str] = Field(default=None, alias="BINANCE_API_SECRET")

    # Bot Configuration
    bet_amount: float = Field(default=1.0, alias="BET_AMOUNT")
    min_odds: float = Field(default=0.4, alias="MIN_ODDS")
    max_odds: float = Field(default=0.65, alias="MAX_ODDS")
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def is_trading_enabled(self) -> bool:
        """Check if trading credentials are configured."""
        return bool(self.wallet_address and self.private_key)

    def get_mode_description(self) -> str:
        """Get a description of the current running mode."""
        if self.dry_run:
            return "DRY RUN MODE (no real bets)"
        if not self.is_trading_enabled():
            return "MONITORING MODE (credentials not configured)"
        return "LIVE TRADING MODE"


# Global settings instance
settings = Settings()

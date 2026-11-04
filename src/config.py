"""Configuration module using Pydantic Settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from .env and environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Alpaca
    ALPACA_API_KEY: str = Field(default="")
    ALPACA_SECRET_KEY: str = Field(default="")
    ALPACA_PAPER: bool = Field(default=True)
    TRADING_MODE: Literal["PAPER", "LIVE"] = Field(default="PAPER")
    BOT_CAPITAL: float = Field(default=500.0)

    # Data & AI
    FINNHUB_API_KEY: str = Field(default="")
    GEMINI_API_KEY: str = Field(default="")
    GEMINI_MODEL: str = Field(default="gemini-flash-lite-latest")

    # Alerts
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    TELEGRAM_CHAT_ID: str = Field(default="")

    # Dashboard & GitHub
    GH_DISPATCH_TOKEN: str = Field(default="")
    DASHBOARD_PASSWORD: str = Field(default="")

    # Directories and files
    DATA_DIR: Path = Field(default_factory=lambda: BASE_DIR / "data")
    CACHE_DIR: Path = Field(default_factory=lambda: BASE_DIR / "data" / "cache")
    CONFIG_DIR: Path = Field(default_factory=lambda: BASE_DIR / "config")
    UNIVERSE_PATH: Path = Field(default_factory=lambda: BASE_DIR / "config" / "universe.csv")


settings = Settings()

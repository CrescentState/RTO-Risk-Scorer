"""
Pydantic Settings for environment-driven configuration.
All secrets and tunable parameters live here.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — env vars override defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── API Keys ──
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API key")

    # ── Model Configuration ──
    GEMINI_MODEL: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model name (verified working: gemini-2.5-flash)",
    )

    # ── Cache Configuration ──
    CACHE_TTL_SECONDS: int = Field(
        default=86400,
        description="Cache time-to-live in seconds (24 hours)",
    )
    CACHE_DIR: str = Field(default="cache", description="Local cache directory")

    # ── Risk Thresholds (Deterministic Rules) ──
    SERIAL_RETURNER_THRESHOLD: float = Field(
        default=0.50,
        description="Return rate above which customer is flagged as serial returner",
    )
    HIGH_VALUE_THRESHOLD: float = Field(
        default=10000.0,
        description="Order value threshold for high-value flag (INR)",
    )
    COD_HIGH_VALUE_THRESHOLD: float = Field(
        default=5000.0,
        description="COD order value threshold for extra risk (INR)",
    )
    HIGH_RTO_PINCODE_THRESHOLD: float = Field(
        default=0.35,
        description="Pincode RTO rate above which pincode is flagged",
    )
    HIGH_COMPLAINT_THRESHOLD: float = Field(
        default=0.70,
        description="Complaint score above which customer is flagged",
    )
    HOSTILE_SENTIMENT_THRESHOLD: float = Field(
        default=-0.40,
        description="Social sentiment below which signals are hostile",
    )
    NEW_ACCOUNT_DAYS: int = Field(
        default=7,
        description="Account age in days below which customer is 'brand new'",
    )
    HIGH_CATEGORY_RTO_THRESHOLD: float = Field(
        default=0.30,
        description="Category return rate above which category is flagged",
    )

    # ── Recommendation Thresholds ──
    AUTO_APPROVE_MAX_SCORE: float = Field(
        default=25.0,
        description="Risk score at or below which order is auto-approved",
    )
    MANUAL_REVIEW_MAX_SCORE: float = Field(
        default=60.0,
        description="Risk score at or below which order goes to manual review",
    )
    MIN_CONFIDENCE_FOR_AUTO: float = Field(
        default=0.50,
        description="Minimum confidence required for any auto-decision",
    )

    # ── Data Paths ──
    CUSTOMERS_CSV: str = Field(default="synthetic_data/customers.csv")
    ORDERS_CSV: str = Field(default="synthetic_data/orders.csv")
    SIGNALS_CSV: str = Field(default="synthetic_data/signals.csv")

    # ── Mock Mode ──
    USE_MOCK_DATA: bool = Field(
        default=False,
        description="If True, agents return hardcoded mock responses (no API calls)",
    )


# Singleton instance — import this everywhere
settings = Settings()
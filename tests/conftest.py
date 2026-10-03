"""Pytest configuration and fixtures."""
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_datasets(tmp_path_factory):
    """Generate all test datasets under tmp_path so tracked CSVs are never rewritten."""
    from core.config import settings

    data_dir = tmp_path_factory.mktemp("synthetic_data")
    cache_dir = tmp_path_factory.mktemp("cache")

    original = {
        "customers": settings.CUSTOMERS_CSV,
        "orders": settings.ORDERS_CSV,
        "signals": settings.SIGNALS_CSV,
        "cache": settings.CACHE_DIR,
    }
    settings.CUSTOMERS_CSV = str(data_dir / "customers.csv")
    settings.ORDERS_CSV = str(data_dir / "orders.csv")
    settings.SIGNALS_CSV = str(data_dir / "signals.csv")
    settings.CACHE_DIR = str(cache_dir)

    # Keep module-level path constants in sync for any legacy references.
    import agents.profile_agent as profile_agent
    import agents.signal_agent as signal_agent

    profile_agent.CUSTOMERS_CSV = settings.CUSTOMERS_CSV
    profile_agent.ORDERS_CSV = settings.ORDERS_CSV
    signal_agent.SIGNALS_CSV = settings.SIGNALS_CSV

    from synthetic_data.generator import generate_dataset

    generate_dataset(num_customers=100, output_dir=str(data_dir))

    yield

    settings.CUSTOMERS_CSV = original["customers"]
    settings.ORDERS_CSV = original["orders"]
    settings.SIGNALS_CSV = original["signals"]
    settings.CACHE_DIR = original["cache"]


@pytest.fixture(autouse=True)
def disable_llm_narratives():
    """Disable LLM narratives by default for all tests."""
    original = os.environ.get("ENABLE_LLM_NARRATIVES")
    os.environ["ENABLE_LLM_NARRATIVES"] = "false"
    # Also need to reset the settings cache
    import core.config
    core.config.settings.ENABLE_LLM_NARRATIVES = False
    yield
    if original is not None:
        os.environ["ENABLE_LLM_NARRATIVES"] = original
    else:
        os.environ.pop("ENABLE_LLM_NARRATIVES", None)
    core.config.settings.ENABLE_LLM_NARRATIVES = (original or "false").lower() == "true"


@pytest.fixture(autouse=True)
def clear_gemini_client():
    """Clear singleton Gemini client between tests."""
    import core.clients
    original_client = core.clients._gemini_client
    original_warned = core.clients._gemini_warned
    core.clients._gemini_client = None
    core.clients._gemini_warned = False
    yield
    core.clients._gemini_client = original_client
    core.clients._gemini_warned = original_warned

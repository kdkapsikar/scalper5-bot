"""Shared fixtures."""
import pytest

from scalpbot import creds


@pytest.fixture(autouse=True)
def _reset_creds_mode(monkeypatch):
    """The API switches the process to strict multi-user mode; keep that from leaking into CLI tests.
    Also: no real network calls to Bybit/Binance from the crypto gap fill unless a test turns it on."""
    monkeypatch.setenv("SCALP_CRYPTO_FILL", "off")
    yield
    creds._STRICT[0] = False
    creds.activate(None)

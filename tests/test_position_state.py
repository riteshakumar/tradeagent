"""Tests for position_state persistence and broker retry classification."""
import json

import pytest

import position_state


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point the store at a temp file and start empty for every test."""
    monkeypatch.setattr(position_state, "_PATH", str(tmp_path / "position_state.json"))
    position_state.clear_all()
    yield
    position_state.clear_all()


def test_save_and_load_roundtrip():
    position_state.peak_prices["AAPL"] = 191.5
    position_state.partial_done["AAPL"] = True
    position_state.position_stops["AAPL"] = 0.06
    position_state.exit_holds["AAPL"] = 2
    position_state.save()

    position_state.clear_all()
    assert position_state.peak_prices == {}

    position_state.load()
    assert position_state.peak_prices == {"AAPL": 191.5}
    assert position_state.partial_done == {"AAPL": True}
    assert position_state.position_stops == {"AAPL": 0.06}
    assert position_state.exit_holds == {"AAPL": 2}


def test_clear_symbol_removes_everywhere_and_persists():
    position_state.peak_prices.update({"AAPL": 191.5, "MSFT": 425.0})
    position_state.partial_done["AAPL"] = True
    position_state.save()

    position_state.clear_symbol("AAPL")

    assert "AAPL" not in position_state.peak_prices
    assert "AAPL" not in position_state.partial_done
    assert position_state.peak_prices == {"MSFT": 425.0}

    # Persisted too
    with open(position_state._PATH) as f:
        payload = json.load(f)
    assert "AAPL" not in payload["peak_prices"]
    assert payload["peak_prices"] == {"MSFT": 425.0}


def test_sync_prunes_stale_symbols_only():
    position_state.peak_prices.update({"AAPL": 191.5, "GONE": 10.0})
    position_state.exit_holds["GONE"] = 1
    position_state.sync({"AAPL"})
    assert position_state.peak_prices == {"AAPL": 191.5}
    assert position_state.exit_holds == {}


def test_load_tolerates_corrupt_file():
    with open(position_state._PATH, "w") as f:
        f.write("{not json")
    position_state.load()  # must not raise
    assert position_state.peak_prices == {}


def test_main_aliases_share_state():
    """main.py aliases the module dicts — mutating one must mutate the other."""
    import main
    main._peak_prices["TSLA"] = 250.0
    assert position_state.peak_prices["TSLA"] == 250.0
    position_state.clear_symbol("TSLA")
    assert "TSLA" not in main._peak_prices


# ── broker retry classification ──────────────────────────────────────────────

def test_retry_classifies_transient_vs_permanent():
    import requests
    import broker

    assert broker._is_transient(requests.exceptions.ConnectionError()) is True
    assert broker._is_transient(requests.exceptions.Timeout()) is True
    assert broker._is_transient(ValueError("bad input")) is False
    assert broker._is_transient(KeyError("x")) is False


def test_retry_classifies_alpaca_api_errors():
    import broker

    try:
        from alpaca.common.exceptions import APIError
    except ImportError:
        pytest.skip("alpaca-py not installed")

    class FakeAPIError(APIError):
        """Subclass so isinstance(exc, APIError) holds without constructor coupling."""

        def __init__(self, code):  # noqa: D401 — bypass APIError.__init__
            Exception.__init__(self, f"status {code}")
            self._code = code

        @property
        def status_code(self):
            return self._code

    assert broker._is_transient(FakeAPIError(429)) is True
    assert broker._is_transient(FakeAPIError(503)) is True
    assert broker._is_transient(FakeAPIError(401)) is False
    assert broker._is_transient(FakeAPIError(404)) is False

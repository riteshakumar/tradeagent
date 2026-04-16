from __future__ import annotations

import shadow_book


def test_shadow_book_tracks_intent_and_realized_trade(tmp_path, monkeypatch):
    path = tmp_path / "shadow_book.json"
    monkeypatch.setattr(shadow_book, "_PATH", str(path))

    shadow_book.clear()
    shadow_book.record_intent("AAPL", "buy", 10, 100.0, "test", 3)
    shadow_book.open_position("AAPL", "long", 10, 100.0, "test", 3)
    shadow_book.update_mark("AAPL", 105.0)
    trade = shadow_book.close_position("AAPL", 105.0, reason="take_profit")

    assert trade is not None
    assert trade["pnl"] > 0

    summary = shadow_book.summary()
    assert summary["realized_pnl"] > 0
    assert len(summary["intents"]) == 1
    assert len(summary["open_positions"]) == 0

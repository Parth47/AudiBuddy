"""Unit tests for APIKeyManager — key rotation, character budgets, add_key."""

import time
import pytest
from unittest.mock import patch

# Mock the settings module before importing
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.api_key_manager import APIKeyManager, _KeyState, RATE_LIMIT_CODES


# ── Helper ─────────────────────────────────────────────────────────────

def _make_manager(**kwargs) -> APIKeyManager:
    """Create a manager with disk persistence disabled."""
    with patch.object(APIKeyManager, "_load_usage"):
        with patch.object(APIKeyManager, "_save_usage"):
            return APIKeyManager(**kwargs)


# ══════════════════════════════════════════════════════════════════════
# BASIC KEY MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

class TestBasicKeyManagement:
    def test_no_keys(self):
        mgr = _make_manager(keys=[], service_name="test")
        assert not mgr.has_keys
        with pytest.raises(RuntimeError, match="No API keys"):
            mgr.get_key()

    def test_single_key(self):
        mgr = _make_manager(keys=["key1"], service_name="test")
        assert mgr.has_keys
        assert mgr.get_key() == "key1"

    def test_deduplication(self):
        mgr = _make_manager(keys=["k1", "k2", "k1", " k2 "], service_name="test")
        assert len(mgr.keys) == 2

    def test_whitespace_stripping(self):
        mgr = _make_manager(keys=["  key1  ", "key2 "], service_name="test")
        assert mgr.keys == ["key1", "key2"]

    def test_empty_strings_filtered(self):
        mgr = _make_manager(keys=["", "  ", "good_key"], service_name="test")
        assert mgr.keys == ["good_key"]


# ══════════════════════════════════════════════════════════════════════
# KEY ROTATION
# ══════════════════════════════════════════════════════════════════════

class TestKeyRotation:
    def test_rotation_on_failure(self):
        mgr = _make_manager(keys=["k1", "k2", "k3"], service_name="test")
        assert mgr.get_key() == "k1"

        mgr.report_failure("k1", status_code=429)
        # After reporting rate limit, should rotate to k2
        key = mgr.get_key()
        assert key == "k2"

    def test_rotation_cycles_through_keys(self):
        mgr = _make_manager(keys=["k1", "k2"], service_name="test")
        mgr.report_failure("k1", status_code=429)
        assert mgr.get_key() == "k2"
        mgr.report_failure("k2", status_code=429)
        # Both on cooldown, should return the one with soonest cooldown expiry
        key = mgr.get_key()
        assert key in ("k1", "k2")

    def test_report_success_increments_calls(self):
        mgr = _make_manager(keys=["k1"], service_name="test")
        mgr.report_success("k1")
        mgr.report_success("k1")
        assert mgr._states["k1"].total_calls == 2


# ══════════════════════════════════════════════════════════════════════
# CHARACTER BUDGET TRACKING
# ══════════════════════════════════════════════════════════════════════

class TestCharacterBudget:
    def test_char_tracking_basic(self):
        with patch("app.services.api_key_manager._current_month", return_value="2026-03"):
            mgr = _make_manager(
                keys=["k1"],
                service_name="test",
                char_limit_per_key=10000,
                char_safety_margin=500,
            )
            mgr.report_chars_used("k1", 5000)
            assert mgr.total_chars_used == 5000
            assert mgr.total_chars_remaining == 5000

    def test_exhaustion_when_over_budget(self):
        with patch("app.services.api_key_manager._current_month", return_value="2026-03"):
            mgr = _make_manager(
                keys=["k1", "k2"],
                service_name="test",
                char_limit_per_key=10000,
                char_safety_margin=500,
            )
            # Push k1 over the safety margin
            mgr.report_chars_used("k1", 9600)
            assert mgr._states["k1"].exhausted is True

    def test_all_keys_exhausted(self):
        with patch("app.services.api_key_manager._current_month", return_value="2026-03"):
            mgr = _make_manager(
                keys=["k1", "k2"],
                service_name="test",
                char_limit_per_key=10000,
                char_safety_margin=500,
            )
            mgr.report_chars_used("k1", 9600)
            mgr.report_chars_used("k2", 9600)
            assert mgr.all_keys_exhausted() is True

    def test_unlimited_budget(self):
        mgr = _make_manager(keys=["k1"], service_name="test", char_limit_per_key=0)
        assert mgr.total_chars_remaining == -1
        assert mgr.all_keys_exhausted() is False

    def test_get_key_for_text_picks_key_with_budget(self):
        with patch("app.services.api_key_manager._current_month", return_value="2026-03"):
            mgr = _make_manager(
                keys=["k1", "k2"],
                service_name="test",
                char_limit_per_key=10000,
                char_safety_margin=500,
            )
            # Exhaust k1
            mgr.report_chars_used("k1", 9600)
            # Now get_key_for_text should skip k1
            key = mgr.get_key_for_text("x" * 1000)
            assert key == "k2"

    def test_month_reset(self):
        """When the month changes, character counters reset."""
        with patch("app.services.api_key_manager._current_month", return_value="2026-02"):
            mgr = _make_manager(
                keys=["k1"],
                service_name="test",
                char_limit_per_key=10000,
                char_safety_margin=500,
            )
            mgr.report_chars_used("k1", 9600)
            assert mgr._states["k1"].exhausted is True

        # Simulate month change
        with patch("app.services.api_key_manager._current_month", return_value="2026-03"):
            # Getting a key should reset the counter
            key = mgr.get_key()
            assert key == "k1"
            assert mgr._states["k1"].exhausted is False
            assert mgr._states["k1"].chars_used == 0


# ══════════════════════════════════════════════════════════════════════
# ADD KEY AT RUNTIME
# ══════════════════════════════════════════════════════════════════════

class TestAddKey:
    def test_add_new_key(self):
        mgr = _make_manager(keys=["k1"], service_name="test")
        assert mgr.add_key("k2") is True
        assert len(mgr.keys) == 2
        assert "k2" in mgr._states

    def test_add_duplicate_key(self):
        mgr = _make_manager(keys=["k1"], service_name="test")
        assert mgr.add_key("k1") is False
        assert len(mgr.keys) == 1

    def test_add_empty_key(self):
        mgr = _make_manager(keys=["k1"], service_name="test")
        assert mgr.add_key("") is False
        assert mgr.add_key("   ") is False

    def test_add_key_to_empty_manager(self):
        mgr = _make_manager(keys=[], service_name="test")
        assert not mgr.has_keys
        assert mgr.add_key("new_key") is True
        assert mgr.has_keys
        assert mgr.get_key() == "new_key"


# ══════════════════════════════════════════════════════════════════════
# STATS & DIAGNOSTICS
# ══════════════════════════════════════════════════════════════════════

class TestStats:
    def test_get_stats_structure(self):
        with patch("app.services.api_key_manager._current_month", return_value="2026-03"):
            mgr = _make_manager(
                keys=["key123456"],
                service_name="test",
                char_limit_per_key=10000,
            )
            stats = mgr.get_stats()
            assert len(stats) == 1
            s = stats[0]
            assert "key_suffix" in s
            assert "total_calls" in s
            assert "failures" in s
            assert "exhausted" in s
            assert "active" in s
            assert "chars_used_this_month" in s
            assert "chars_limit" in s
            assert "chars_remaining" in s

    def test_stats_reflect_usage(self):
        with patch("app.services.api_key_manager._current_month", return_value="2026-03"):
            mgr = _make_manager(
                keys=["key123456"],
                service_name="test",
                char_limit_per_key=10000,
            )
            mgr.report_success("key123456")
            mgr.report_chars_used("key123456", 3000)
            stats = mgr.get_stats()
            assert stats[0]["total_calls"] == 1
            assert stats[0]["chars_used_this_month"] == 3000

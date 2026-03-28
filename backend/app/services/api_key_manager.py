"""API Key Rotation Manager — automatic key cycling for TTS and LLM APIs.

Supports two rotation strategies:
  1. Error-based  — rotate when a key hits rate-limit / quota errors (standard)
  2. Character-budget — proactively rotate BEFORE hitting a character limit
     (critical for ElevenLabs free tier: 10,000 chars/month per key)

The character-budget mode keeps a running counter of characters sent through
each key.  When a key's counter approaches its monthly budget, the manager
seamlessly switches to the next key — no error, no disruption.

Usage:
    # Standard (error-based rotation)
    manager = APIKeyManager(keys=["k1", "k2"], service_name="openai-tts")

    # Character-budget rotation (e.g. ElevenLabs free tier)
    manager = APIKeyManager(
        keys=["k1", "k2", "k3"],
        service_name="elevenlabs",
        char_limit_per_key=10000,     # monthly free-tier limit
        char_safety_margin=500,       # switch 500 chars early to be safe
    )
    key = manager.get_key_for_text(text)  # picks a key that has budget left
    manager.report_chars_used(key, len(text))
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# HTTP status codes that indicate rate-limit or quota exhaustion.
# 403 is intentionally excluded — it means "permission denied" (invalid key,
# API not enabled, region blocked), not quota.  A 403 key should NOT be
# cooled-down — it will never start working after a timeout.
RATE_LIMIT_CODES = {429, 402}

# How long (seconds) to cool-down a key before re-trying it
KEY_COOLDOWN_SECONDS = 60

# Where to persist character usage counters (survives server restarts)
_USAGE_DIR = Path(os.getenv("AUDIO_OUTPUT_DIR", "./audio_output")) / ".key_usage"


@dataclass
class _KeyState:
    """Internal bookkeeping for a single API key."""
    key: str
    total_calls: int = 0
    failures: int = 0
    last_failure_time: float = 0.0
    exhausted: bool = False
    cooldown_until: float = 0.0
    # Character-budget tracking
    chars_used: int = 0               # characters processed this period
    chars_used_month: str = ""        # "2026-03" — the month these counts belong to


@dataclass
class APIKeyManager:
    """Round-robin API key manager with character-budget awareness.

    Parameters
    ----------
    keys : list[str]
        One or more API keys.
    service_name : str
        Label for logging (e.g. "elevenlabs").
    char_limit_per_key : int
        Monthly character budget per key.  0 = unlimited (no proactive switching).
    char_safety_margin : int
        Switch to next key when remaining budget drops below this.
    """
    keys: list[str]
    service_name: str = "api"
    char_limit_per_key: int = 0
    char_safety_margin: int = 500
    _states: dict[str, _KeyState] = field(default_factory=dict, init=False, repr=False)
    _current_index: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        clean: list[str] = []
        for k in self.keys:
            k = k.strip()
            if k and k not in seen:
                seen.add(k)
                clean.append(k)
        self.keys = clean
        self._states = {k: _KeyState(key=k) for k in self.keys}
        if not self.keys:
            logger.warning("[%s] No API keys configured.", self.service_name)
        # Load persisted usage counters from disk
        self._load_usage()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def has_keys(self) -> bool:
        return len(self.keys) > 0

    def add_key(self, key: str) -> bool:
        """Add a new API key at runtime. Returns False if duplicate or empty."""
        key = key.strip()
        if not key or key in self._states:
            return False
        self.keys.append(key)
        self._states[key] = _KeyState(key=key)
        logger.info("[%s] New API key added at runtime (...%s). Total keys: %d",
                     self.service_name, key[-6:], len(self.keys))
        return True

    @property
    def total_chars_used(self) -> int:
        """Total characters used across ALL keys this month."""
        month = _current_month()
        return sum(
            s.chars_used for s in self._states.values() if s.chars_used_month == month
        )

    @property
    def total_chars_remaining(self) -> int:
        """Total characters remaining across ALL keys."""
        if self.char_limit_per_key <= 0:
            return -1  # unlimited
        month = _current_month()
        total = 0
        for s in self._states.values():
            used = s.chars_used if s.chars_used_month == month else 0
            total += max(0, self.char_limit_per_key - used)
        return total

    def get_key(self) -> str:
        """Return the best available key (standard, no character check)."""
        return self._find_available_key(chars_needed=0)

    def get_key_for_text(self, text: str) -> str:
        """Return a key that has enough character budget for the given text.

        If char_limit_per_key is 0 (unlimited), this is identical to get_key().
        Otherwise it picks the first key with enough remaining budget.
        """
        return self._find_available_key(chars_needed=len(text))

    def report_success(self, key: str) -> None:
        state = self._states.get(key)
        if state:
            state.total_calls += 1

    def report_chars_used(self, key: str, char_count: int) -> None:
        """Record that *char_count* characters were sent through *key*.

        Automatically resets the counter when the month changes.
        Persists the updated total to disk.
        """
        state = self._states.get(key)
        if not state:
            return

        month = _current_month()
        if state.chars_used_month != month:
            state.chars_used = 0
            state.chars_used_month = month
            state.exhausted = False

        state.chars_used += char_count
        remaining = self.char_limit_per_key - state.chars_used if self.char_limit_per_key > 0 else -1

        logger.info(
            "[%s] Key ...%s used %d chars (total this month: %d / %s, remaining: %s)",
            self.service_name, key[-6:], char_count, state.chars_used,
            self.char_limit_per_key or "unlimited",
            remaining if remaining >= 0 else "unlimited",
        )

        # Proactively exhaust the key if it's over budget
        if self.char_limit_per_key > 0 and state.chars_used >= (self.char_limit_per_key - self.char_safety_margin):
            logger.warning(
                "[%s] Key ...%s approaching limit (%d/%d chars). Marking exhausted and rotating.",
                self.service_name, key[-6:], state.chars_used, self.char_limit_per_key,
            )
            state.exhausted = True
            self._rotate()

        self._save_usage()

    def report_failure(self, key: str, status_code: int | None = None, error_msg: str = "") -> None:
        state = self._states.get(key)
        if not state:
            return

        state.failures += 1
        state.last_failure_time = time.time()

        is_rate_limit = status_code in RATE_LIMIT_CODES if status_code else False
        is_quota = status_code == 402 or "quota" in error_msg.lower() or "limit" in error_msg.lower()

        if is_rate_limit or is_quota:
            state.cooldown_until = time.time() + KEY_COOLDOWN_SECONDS
            state.exhausted = is_quota
            logger.warning(
                "[%s] Key ...%s hit %s (HTTP %s). Rotating. Error: %s",
                self.service_name, key[-6:],
                "quota limit" if is_quota else "rate limit",
                status_code, error_msg[:120],
            )
            self._rotate()
        else:
            logger.warning(
                "[%s] Key ...%s failed (HTTP %s): %s",
                self.service_name, key[-6:], status_code, error_msg[:120],
            )

    def all_keys_exhausted(self) -> bool:
        """True if every key has used up its character budget this month."""
        if self.char_limit_per_key <= 0:
            return False
        month = _current_month()
        for s in self._states.values():
            used = s.chars_used if s.chars_used_month == month else 0
            if used < (self.char_limit_per_key - self.char_safety_margin):
                return False
        return True

    def get_stats(self) -> list[dict]:
        now = time.time()
        month = _current_month()
        return [
            {
                "key_suffix": f"...{s.key[-6:]}",
                "total_calls": s.total_calls,
                "failures": s.failures,
                "exhausted": s.exhausted,
                "cooldown_remaining": max(0, int(s.cooldown_until - now)) if s.cooldown_until else 0,
                "active": s.key == self.keys[self._current_index],
                "chars_used_this_month": s.chars_used if s.chars_used_month == month else 0,
                "chars_limit": self.char_limit_per_key or "unlimited",
                "chars_remaining": max(0, self.char_limit_per_key - s.chars_used)
                    if self.char_limit_per_key > 0 and s.chars_used_month == month else "unlimited",
            }
            for s in self._states.values()
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_available_key(self, chars_needed: int) -> str:
        if not self.keys:
            raise RuntimeError(f"[{self.service_name}] No API keys configured.")

        now = time.time()
        month = _current_month()
        n = len(self.keys)
        budget_mode = self.char_limit_per_key > 0 and chars_needed > 0

        for _ in range(n):
            key = self.keys[self._current_index]
            state = self._states[key]

            # Reset cooldown if expired
            if state.cooldown_until and now >= state.cooldown_until:
                state.cooldown_until = 0.0
                state.exhausted = False

            # Reset month if it changed
            if state.chars_used_month != month:
                state.chars_used = 0
                state.chars_used_month = month
                state.exhausted = False

            if state.exhausted or state.cooldown_until > 0:
                self._current_index = (self._current_index + 1) % n
                continue

            # In budget mode, check if this key has enough remaining chars
            if budget_mode:
                remaining = self.char_limit_per_key - state.chars_used
                if remaining < (chars_needed + self.char_safety_margin):
                    logger.info(
                        "[%s] Key ...%s has only %d chars left (need %d + %d margin). Skipping.",
                        self.service_name, key[-6:], remaining, chars_needed, self.char_safety_margin,
                    )
                    state.exhausted = True
                    self._current_index = (self._current_index + 1) % n
                    continue

            return key

        # All keys checked — in budget mode, find the one with most chars remaining
        if budget_mode:
            best = max(
                self._states.values(),
                key=lambda s: (self.char_limit_per_key - s.chars_used)
                    if s.chars_used_month == month else self.char_limit_per_key,
            )
            remaining = self.char_limit_per_key - best.chars_used if best.chars_used_month == month else self.char_limit_per_key
            if remaining > 0:
                logger.warning(
                    "[%s] All keys near limit. Using key ...%s with %d chars remaining.",
                    self.service_name, best.key[-6:], remaining,
                )
                return best.key

        # Fallback: return the key whose cooldown expires soonest
        soonest = min(self._states.values(), key=lambda s: s.cooldown_until or float("inf"))
        if soonest.cooldown_until:
            return soonest.key

        raise RuntimeError(f"[{self.service_name}] All API keys exhausted for this month.")

    def _rotate(self) -> None:
        if len(self.keys) > 1:
            old_idx = self._current_index
            self._current_index = (self._current_index + 1) % len(self.keys)
            logger.info(
                "[%s] Rotated from key ...%s → ...%s",
                self.service_name,
                self.keys[old_idx][-6:],
                self.keys[self._current_index][-6:],
            )

    # ------------------------------------------------------------------
    # Persistence — survive server restarts
    # ------------------------------------------------------------------

    def _usage_file(self) -> Path:
        return _USAGE_DIR / f"{self.service_name}_usage.json"

    def _save_usage(self) -> None:
        """Persist character usage counters to disk."""
        try:
            _USAGE_DIR.mkdir(parents=True, exist_ok=True)
            data = {}
            for s in self._states.values():
                data[s.key[-8:]] = {
                    "chars_used": s.chars_used,
                    "month": s.chars_used_month,
                }
            self._usage_file().write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.debug("[%s] Could not save usage data: %s", self.service_name, exc)

    def _load_usage(self) -> None:
        """Load persisted character usage counters from disk."""
        try:
            path = self._usage_file()
            if not path.exists():
                return
            data = json.loads(path.read_text())
            month = _current_month()
            for s in self._states.values():
                entry = data.get(s.key[-8:])
                if entry and entry.get("month") == month:
                    s.chars_used = entry.get("chars_used", 0)
                    s.chars_used_month = month
                    logger.info(
                        "[%s] Loaded persisted usage for key ...%s: %d chars this month",
                        self.service_name, s.key[-6:], s.chars_used,
                    )
        except Exception as exc:
            logger.debug("[%s] Could not load usage data: %s", self.service_name, exc)


def _current_month() -> str:
    """Return the current month as 'YYYY-MM' for budget reset tracking."""
    return time.strftime("%Y-%m")

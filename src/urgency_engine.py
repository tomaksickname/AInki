#!/usr/bin/env python3
"""
AInki — Urgency Engine
======================

Decides which practice words appear as context in AI-generated sentences.

Responsibilities:
    - Two-phase selection:
        Phase 1 (random): give every practice word one exposure
        Phase 2 (urgency): prioritize words by urgency score
    - Score urgency based on:
        - time since last seen  (70%)
        - total exposures       (30%)
    - Record context exposures (keep both data stores in sync)
    - Detect phase transition (random → urgency)

Design:
    - Reads from: vocabulary_data.json (per-word urgency_data)
    - Reads from: exposure_data.json (phase, unexposed list)
    - Returns: list of unique practice words
    - Caller (daily_generator) handles sentence generation

Data sync:
    - vocabulary_data.json[word].urgency_data  = source of truth per word
    - exposure_data.json["exposure_history"]   = fast lookup (mirror)
    - exposure_data.json["unexposed"]          = remaining in phase 1
    - exposure_data.json["phase"]              = "random" | "urgency"
"""

import logging
import random
from datetime import datetime
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


class UrgencyEngine:
    """Two-phase urgency-based practice word selector."""

    # ==================== INITIALIZATION ====================

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize urgency engine.

        Args:
            config: Full AInki config dict.
        """
        urg = config.get("urgency_settings", {})

        self.time_weight = urg.get("time_weight", 0.7)
        self.exposure_weight = urg.get("exposure_weight", 0.3)

        self.max_days_between_exposures = urg.get("max_days_between_exposures", 40)
        self.min_days_between_exposures = urg.get("min_days_between_exposures", 14)

        self.target_exposures_per_word = urg.get("target_exposures_per_word", 10)

        self.learning_bonus = urg.get("learning_bonus", 0.3)
        self.lapse_bonus = urg.get("lapse_bonus", 0.2)
        self.overdue_bonus = urg.get("overdue_bonus", 0.1)

        self.phase_1_days = urg.get("phase_1_days", 42)

        # Sanity check
        if abs(self.time_weight + self.exposure_weight - 1.0) > 0.001:
            logger.warning(
                f"urgency weights don't sum to 1.0: "
                f"time={self.time_weight}, exposure={self.exposure_weight}"
            )

        logger.info(
            f"UrgencyEngine initialized: "
            f"time={self.time_weight}, exposure={self.exposure_weight}, "
            f"max_gap={self.max_days_between_exposures}d"
        )

    # ==================== MAIN SELECTION ====================

    def select_practice_words(
        self,
        words: List[Dict[str, Any]],
        exposure_data: Dict[str, Any],
        count: int,
        now: Optional[datetime] = None,
    ) -> List[str]:
        """
        Select the most urgent N practice words.

        Uses phase from exposure_data:
            "random"  → pick from unexposed list, remove as we go
            "urgency" → score every practice word, take top N

        Args:
            words:          Full list of word dicts (from vocabulary_data.json).
            exposure_data:  Full exposure tracking dict (from exposure_data.json).
            count:          How many unique practice words to return.
            now:            Current time (for testing).

        Returns:
            List of unique practice word strings (words, not dicts).
        """
        if now is None:
            now = datetime.now()

        phase = exposure_data.get("phase", "random")

        if phase == "random":
            selected = self._select_random(exposure_data, count)
            # If random pool ran dry, switch to urgency
            if len(selected) < count:
                logger.info(
                    f"Random pool exhausted ({len(selected)}/{count} selected). "
                    f"Switching to urgency phase."
                )
                exposure_data["phase"] = "urgency"
                remaining = count - len(selected)
                selected += self._select_by_urgency(words, remaining, now)
        else:
            selected = self._select_by_urgency(words, count, now)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for w in selected:
            if w not in seen:
                seen.add(w)
                unique.append(w)

        logger.debug(
            f"Selected {len(unique)} unique practice words "
            f"(phase={exposure_data.get('phase')})"
        )
        return unique[:count]

    # ==================== PHASE 1: RANDOM ====================

    def _select_random(
        self,
        exposure_data: Dict[str, Any],
        count: int,
    ) -> List[str]:
        """
        Phase 1: pick random words from the unexposed pool.
        Removes them from the pool as they're picked.
        """
        unexposed = exposure_data.get("unexposed", [])
        if not unexposed:
            return []

        # Pick up to `count` random words
        n = min(count, len(unexposed))
        picked = random.sample(unexposed, n)

        # Remove picked words from unexposed pool
        picked_set = set(picked)
        exposure_data["unexposed"] = [
            w for w in unexposed if w not in picked_set
        ]

        logger.debug(
            f"Random phase: picked {n}, "
            f"{len(exposure_data['unexposed'])} still unexposed"
        )
        return picked

    # ==================== PHASE 2: URGENCY ====================

    def _select_by_urgency(
        self,
        words: List[Dict[str, Any]],
        count: int,
        now: datetime,
    ) -> List[str]:
        """
        Phase 2: score every unique practice word, return top N.

        Uses vocabulary_data.json[word].urgency_data as source of truth.
        """
        # Build urgency scores for unique practice words
        scores = []
        seen = set()

        for w in words:
            if w.get("decision") != "practice":
                continue

            word_text = w.get("word")
            if not word_text or word_text in seen:
                continue
            seen.add(word_text)

            urgency = self.calculate_urgency(w, now)
            scores.append((urgency, word_text))

        # Sort: highest urgency first
        scores.sort(key=lambda x: x[0], reverse=True)

        top = [word for _, word in scores[:count]]

        top_urgency = scores[0][0] if scores else 0.0
        logger.debug(
            f"Urgency phase: scored {len(scores)} unique practice words, "
            f"top urgency = {top_urgency:.3f}"
        )
        return top

    # ==================== URGENCY SCORE ====================

    def calculate_urgency(
        self,
        word: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> float:
        """
        Compute urgency score (0.0 – 1.0+) for a single word.

        urgency = time_score * time_weight
                + exposure_score * exposure_weight
                + bonuses

        Bonuses:
            + learning_bonus  if srs_data.state == "learning"
            + lapse_bonus     if srs_data.lapses >= 2
            + overdue_bonus   if srs_data.due_date < now
        """
        if now is None:
            now = datetime.now()

        urg_data = word.get("urgency_data", {})
        srs_data = word.get("srs_data", {})

        # ---------- Time component ----------
        last_seen_str = urg_data.get("last_seen")
        if last_seen_str:
            try:
                last_seen = datetime.fromisoformat(last_seen_str)
                days_since = (now - last_seen).days
            except (ValueError, TypeError):
                days_since = self.max_days_between_exposures
        else:
            # Never seen → maximum time urgency
            days_since = self.max_days_between_exposures

        time_score = self._time_score(days_since)

        # ---------- Exposure component ----------
        total_exp = urg_data.get("total_exposures", 0)
        exposure_score = self._exposure_score(total_exp)

        # ---------- Base urgency ----------
        urgency = (
            time_score * self.time_weight
            + exposure_score * self.exposure_weight
        )

        # ---------- Bonuses ----------
        if srs_data.get("state") == "learning":
            urgency += self.learning_bonus

        if srs_data.get("lapses", 0) >= 2:
            urgency += self.lapse_bonus

        due_str = srs_data.get("due_date")
        if due_str:
            try:
                due = datetime.fromisoformat(due_str)
                if due < now:
                    urgency += self.overdue_bonus
            except (ValueError, TypeError):
                pass

        return urgency

    def _time_score(self, days_since: int) -> float:
        """Map days-since-last-seen to a 0.0–1.0 score."""
        m = self.max_days_between_exposures

        if days_since >= m:
            return 1.0
        if days_since >= m * 0.75:
            return 0.8
        if days_since >= m * 0.5:
            return 0.6
        if days_since >= m * 0.35:
            return 0.4
        if days_since >= m * 0.2:
            return 0.2
        return 0.0

    def _exposure_score(self, total_exp: int) -> float:
        """Map total-exposures to a 0.0–1.0 score (fewer = higher)."""
        target = self.target_exposures_per_word

        if total_exp <= target * 0.2:
            return 1.0
        if total_exp <= target * 0.4:
            return 0.7
        if total_exp <= target * 0.7:
            return 0.4
        if total_exp <= target:
            return 0.2
        return 0.0

    # ==================== RECORD EXPOSURE ====================

    def record_context_exposure(
        self,
        word: Dict[str, Any],
        sentence_data: Optional[Dict[str, Any]],
        exposure_data: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> None:
        """
        Record that a word was just used as context in a sentence.

        Updates BOTH data stores:
            vocabulary_data.json[word].urgency_data  (source of truth)
            exposure_data.json["exposure_history"]   (mirror)

        Args:
            word:           The word dict from vocabulary_data.json.
            sentence_data:  Optional dict with sentence info (for history).
            exposure_data:  The exposure tracking dict (from exposure_data.json).
            now:            Current time.
        """
        if now is None:
            now = datetime.now()

        word_text = word.get("word")
        if not word_text:
            return

        timestamp = now.isoformat()

        # ---------- Update vocabulary_data (source of truth) ----------
        urg = word.setdefault("urgency_data", {})
        urg["total_exposures"] = urg.get("total_exposures", 0) + 1
        urg["context_exposures"] = urg.get("context_exposures", 0) + 1
        urg["last_seen"] = timestamp
        urg.setdefault("exposure_history", []).append(timestamp)

        # ---------- Update exposure_data.json (mirror) ----------
        history = exposure_data.setdefault("exposure_history", {})
        entry = history.setdefault(
            word_text,
            {"total_exposures": 0, "last_seen": None},
        )
        entry["total_exposures"] = urg["total_exposures"]
        entry["last_seen"] = timestamp

    def record_review_exposure(
        self,
        word: Dict[str, Any],
        exposure_data: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> None:
        """
        Record an active review (from SRS engine).

        Increments total_exposures but NOT context_exposures.
        """
        if now is None:
            now = datetime.now()

        word_text = word.get("word")
        if not word_text:
            return

        timestamp = now.isoformat()

        urg = word.setdefault("urgency_data", {})
        urg["total_exposures"] = urg.get("total_exposures", 0) + 1
        urg["review_exposures"] = urg.get("review_exposures", 0) + 1
        urg["last_seen"] = timestamp
        urg.setdefault("exposure_history", []).append(timestamp)

        history = exposure_data.setdefault("exposure_history", {})
        entry = history.setdefault(
            word_text,
            {"total_exposures": 0, "last_seen": None},
        )
        entry["total_exposures"] = urg["total_exposures"]
        entry["last_seen"] = timestamp

    # ==================== PHASE MANAGEMENT ====================

    def check_phase(self, exposure_data: Dict[str, Any]) -> str:
        """
        Determine current phase based on unexposed list.

        Returns "random" or "urgency". Also writes it into exposure_data.
        """
        unexposed = exposure_data.get("unexposed", [])

        if unexposed:
            exposure_data["phase"] = "random"
        else:
            if exposure_data.get("phase") != "urgency":
                logger.info("Phase transition: random → urgency")
            exposure_data["phase"] = "urgency"

        return exposure_data["phase"]

    # ==================== STATS ====================

    def stats(
        self,
        words: List[Dict[str, Any]],
        exposure_data: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Return summary stats for monitoring."""
        if now is None:
            now = datetime.now()

        practice_words = [w for w in words if w.get("decision") == "practice"]
        unique_practice = {w["word"] for w in practice_words}

        unexposed = len(exposure_data.get("unexposed", []))

        # Urgency distribution
        buckets = {"critical": 0, "high": 0, "medium": 0, "low": 0, "fresh": 0}
        total_urgency = 0.0
        count = 0

        for word_text in unique_practice:
            # Find first occurrence
            word = next((w for w in practice_words if w["word"] == word_text), None)
            if not word:
                continue

            u = self.calculate_urgency(word, now)
            total_urgency += u
            count += 1

            if u >= 0.8:
                buckets["critical"] += 1
            elif u >= 0.6:
                buckets["high"] += 1
            elif u >= 0.4:
                buckets["medium"] += 1
            elif u >= 0.2:
                buckets["low"] += 1
            else:
                buckets["fresh"] += 1

        avg_urgency = total_urgency / count if count else 0.0

        return {
            "phase": exposure_data.get("phase", "random"),
            "days_running": exposure_data.get("days_running", 0),
            "total_practice_cards": len(practice_words),
            "unique_practice_words": len(unique_practice),
            "unexposed_remaining": unexposed,
            "avg_urgency": round(avg_urgency, 3),
            "urgency_buckets": buckets,
        }


# ==================== STANDALONE TEST ====================

if __name__ == "__main__":
    import sys
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    sys.path.insert(0, ".")
    from file_manager import FileManager

    print("Testing UrgencyEngine...")
    print()

    fm = FileManager()
    fm.ensure_all_files()

    config = fm.get_config()
    engine = UrgencyEngine(config)

    working = fm.load_working_data()
    exposure = fm.load_exposure_data()
    words = working["decisions"]

    print("=== Initial stats ===")
    stats = engine.stats(words, exposure)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print()

    print("=== Select 240 practice words (day 1, random phase) ===")
    selected = engine.select_practice_words(words, exposure, count=240)
    print(f"  Selected: {len(selected)} unique words")
    print(f"  First 10: {selected[:10]}")
    print()

    print("=== Simulate recording context exposures ===")
    for word_text in selected[:5]:
        word = next((w for w in words if w["word"] == word_text), None)
        if word:
            engine.record_context_exposure(word, None, exposure)
    print(f"  Recorded 5 context exposures")
    print()

    print("=== Check urgency of one exposed word ===")
    test_word = next((w for w in words if w["word"] == selected[0]), None)
    if test_word:
        u = engine.calculate_urgency(test_word)
        print(f"  {test_word['word']}: urgency={u:.3f}")
        print(f"    total_exposures={test_word['urgency_data']['total_exposures']}")
        print(f"    last_seen={test_word['urgency_data']['last_seen']}")
    print()

    print("=== Phase check ===")
    phase = engine.check_phase(exposure)
    print(f"  Phase: {phase}")
    print(f"  Unexposed remaining: {len(exposure['unexposed'])}")
    print()

    print("=== Stats after 240 selections ===")
    stats = engine.stats(words, exposure)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print()

    print("✅ UrgencyEngine test complete")
    print()
    print("⚠️  Note: test modified data in-memory only — NOT saved.")

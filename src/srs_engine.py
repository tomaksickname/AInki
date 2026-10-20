#!/usr/bin/env python3
"""
AInki — SRS Engine
==================

Implements the SM-2 spaced repetition algorithm with learning steps.

Responsibilities:
    - Identify new cards (never reviewed) → next N by rank
    - Identify due reviews (last_reviewed set, due_date <= now)
    - Update a card's SRS data when the user rates it
    - Handle learning steps, graduating, ease factors
    - Detect leeches

Design:
    - Stateless engine: reads from a word dict, returns updated dict
    - The FileManager handles persistence
    - Uses config from config.json for all tunable parameters

Match to Anki defaults:
    - 10 new cards/day
    - Learning steps: 1, 10, 30 minutes
    - Graduating interval: 1 day
    - Starting ease: 2.5
    - Hard interval multiplier: 1.2
    - Easy bonus: 1.3
"""

import logging
from datetime import datetime, timedelta, time as dtime
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


class SRSEngine:
    """SM-2 style SRS scheduler for AInki."""

    # ==================== INITIALIZATION ====================

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize SRS engine.

        Args:
            config: Full AInki config dict (from config.json)
        """
        srs = config.get("srs_settings", {})

        # Card intake
        self.new_cards_per_day = srs.get("new_cards_per_day", 10)
        self.max_reviews_per_day = srs.get("max_reviews_per_day", None)

        # Learning steps (in minutes)
        self.learning_steps_minutes = srs.get("learning_steps_minutes", [1, 10, 30])

        # Intervals (in days)
        self.graduating_interval_days = srs.get("graduating_interval_days", 1)
        self.easy_interval_days = srs.get("easy_interval_days", 4)

        # Ease factors
        self.starting_ease = srs.get("starting_ease", 2.5)
        self.easy_bonus = srs.get("easy_bonus", 1.3)
        self.interval_modifier = srs.get("interval_modifier", 1.0)
        self.hard_interval_multiplier = srs.get("hard_interval_multiplier", 1.2)
        self.min_ease_factor = srs.get("min_ease_factor", 1.3)
        self.max_ease_factor = srs.get("max_ease_factor", 3.0)

        # Leech handling
        self.leech_threshold = srs.get("leech_threshold", 8)
        self.leech_action = srs.get("leech_action", "suspend")

        # Review ordering
        self.review_order = srs.get("review_order", "overdue_first")

        logger.info(
            f"SRSEngine initialized: {self.new_cards_per_day} new/day, "
            f"steps={self.learning_steps_minutes}min, ease={self.starting_ease}"
        )

    # ==================== QUERY: NEW CARDS ====================

    def get_new_cards(
        self,
        words: List[Dict[str, Any]],
        count: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return the next N brand-new cards (never reviewed).

        Logic:
            1. Filter to decision == "new"
            2. Filter to srs_data.last_reviewed == None  (never shown)
            3. Sort by rank ascending
            4. Take first N

        Args:
            words: Full list of word dicts from vocabulary_data.json
            count: How many to return. Defaults to config value.

        Returns:
            List of word dicts (references into `words`, not copies).
        """
        if count is None:
            count = self.new_cards_per_day

        fresh = [
            w for w in words
            if w.get("decision") == "new"
            and w.get("srs_data", {}).get("last_reviewed") is None
        ]

        # decisions.json is sorted by rank, but be explicit for safety
        fresh.sort(key=lambda w: w.get("rank", 0))

        selected = fresh[:count]

        logger.debug(
            f"New cards: {len(fresh)} unreviewed, serving {len(selected)}"
        )
        return selected

    # ==================== QUERY: DUE REVIEWS ====================

    def get_due_reviews(
        self,
        words: List[Dict[str, Any]],
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return all cards due for review today.

        Anki-like behavior: a card is "due" if its due_date falls on
        or before today's calendar date, regardless of the exact hour.
        This means a card scheduled for 20:42 tonight is due as soon as
        the day starts, not at 20:42.

        Logic:
            1. Filter to srs_data.last_reviewed != None  (already in system)
            2. Learning cards are ALWAYS due (frontend queue handles spacing)
            3. Review cards: due_date <= end of today
            4. Skip suspended / leeched cards
            5. Sort by due_date ascending (most overdue first)

        Args:
            words: Full list of word dicts.
            now: Current time. Defaults to datetime.now().

        Returns:
            List of word dicts sorted by urgency (most overdue first).
        """
        if now is None:
            now = datetime.now()

        # End of today = today at 23:59:59.999999
        end_of_today = datetime.combine(now.date(), dtime.max)

        due = []
        for w in words:
            srs = w.get("srs_data", {})

            # Skip cards never reviewed (those are "new")
            if srs.get("last_reviewed") is None:
                continue

            # Skip suspended cards
            if srs.get("is_leech") and self.leech_action == "suspend":
                continue

            # Learning cards are ALWAYS due.
            # Their due_date is a within-session retry timer (minutes),
            # which we deliberately ignore — the frontend queue handles
            # the spacing, and a session ends only when every card has
            # graduated out of learning.
            if srs.get("state") == "learning":
                due.append(w)
                continue

            # Review cards: due if their due_date is on or before today.
            due_date_str = srs.get("due_date")
            if due_date_str is None:
                continue

            try:
                due_date = datetime.fromisoformat(due_date_str)
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid due_date for {w.get('word')}: {due_date_str}"
                )
                continue

            if due_date <= end_of_today:
                due.append(w)

        # Sort by most overdue first
        if self.review_order == "overdue_first":
            due.sort(key=lambda w: w["srs_data"].get("due_date", "") or "")
        elif self.review_order == "random":
            import random
            random.shuffle(due)
        # else: leave as-is (file order)

        # Apply daily cap if configured
        if self.max_reviews_per_day is not None:
            due = due[: self.max_reviews_per_day]

        logger.debug(f"Due reviews: {len(due)}")
        return due

    # ==================== QUERY: COMBINED ====================

    def get_today_cards(
        self,
        words: List[Dict[str, Any]],
        now: Optional[datetime] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Return both new cards and due reviews for today.

        Ensures no overlap: a card cannot be both "new" and "review".

        Returns:
            {
                "new": [...],       # up to 10 fresh cards
                "reviews": [...],   # all due reviews
                "total": int
            }
        """
        if now is None:
            now = datetime.now()

        new_cards = self.get_new_cards(words)

        # New cards are about to be "shown" — exclude them from reviews
        new_ranks = {w.get("rank") for w in new_cards}

        reviews = [
            w for w in self.get_due_reviews(words, now)
            if w.get("rank") not in new_ranks
        ]

        return {
            "new": new_cards,
            "reviews": reviews,
            "total": len(new_cards) + len(reviews),
        }

    # ==================== UPDATE: CARD REVIEWED ====================

    def rate_card(
        self,
        word: Dict[str, Any],
        rating: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Update a word's SRS data based on the user's rating.

        Args:
            word:   The word dict (modified in place).
            rating: One of "again", "hard", "good", "easy".
            now:    Current time (defaults to datetime.now()).

        Returns:
            The updated word dict.
        """
        if rating not in ("again", "hard", "good", "easy"):
            raise ValueError(f"Invalid rating: {rating}")

        if now is None:
            now = datetime.now()

        srs = word.setdefault("srs_data", {})
        state = srs.get("state", "learning")

        # Always record the review event
        srs["last_reviewed"] = now.isoformat()
        srs["review_count"] = srs.get("review_count", 0) + 1

        if state == "learning":
            self._update_learning(word, rating, now)
        elif state == "review":
            self._update_review(word, rating, now)
        else:
            logger.warning(
                f"Unknown SRS state '{state}' for {word.get('word')}, "
                f"treating as review"
            )
            srs["state"] = "review"
            self._update_review(word, rating, now)

        # Check leech status
        self._check_leech(word)

        return word

    # ==================== LEARNING PHASE ====================

    def _update_learning(
        self,
        word: Dict[str, Any],
        rating: str,
        now: datetime,
    ) -> None:
        """
        Handle rating for a card in the learning phase.

        Learning steps: [1, 10, 30] minutes.
        On "good": advance to next step, or graduate if last step.
        On "hard": repeat current step.
        On "again": back to step 0.
        On "easy": graduate immediately (skip remaining steps).
        """
        srs = word["srs_data"]
        step_index = srs.get("step_index", 0)
        steps = self.learning_steps_minutes

        if rating == "again":
            # Restart learning, first step
            srs["step_index"] = 0
            srs["lapses"] = srs.get("lapses", 0) + 1
            due = now + timedelta(minutes=steps[0])
            srs["due_date"] = due.isoformat()

        elif rating == "hard":
            # Repeat current step
            step_idx = min(step_index, len(steps) - 1)
            due = now + timedelta(minutes=steps[step_idx])
            srs["due_date"] = due.isoformat()

        elif rating == "good":
            next_index = step_index + 1
            if next_index < len(steps):
                # Advance to next step
                srs["step_index"] = next_index
                due = now + timedelta(minutes=steps[next_index])
                srs["due_date"] = due.isoformat()
            else:
                # Graduate to review phase
                self._graduate(word, now)

        elif rating == "easy":
            # Graduate immediately
            srs["ease_factor"] = min(
                self.max_ease_factor,
                srs.get("ease_factor", self.starting_ease) + 0.15,
            )
            self._graduate(word, now, easy=True)

    def _graduate(
        self,
        word: Dict[str, Any],
        now: datetime,
        easy: bool = False,
    ) -> None:
        """Move a card from learning to review phase."""
        srs = word["srs_data"]

        if easy:
            interval = self.easy_interval_days
        else:
            interval = self.graduating_interval_days

        srs["state"] = "review"
        srs["step_index"] = 0
        srs["interval_days"] = interval
        srs["ease_factor"] = srs.get("ease_factor", self.starting_ease)
        srs["due_date"] = (now + timedelta(days=interval)).isoformat()

    # ==================== REVIEW PHASE ====================

    def _update_review(
        self,
        word: Dict[str, Any],
        rating: str,
        now: datetime,
    ) -> None:
        """
        Handle rating for a card in the review phase.

        Uses modified SM-2:
            again → back to learning, interval reset
            hard  → interval *= hard_interval_multiplier, ease -= 0.15
            good  → interval *= ease
            easy  → interval *= ease * easy_bonus, ease += 0.15
        """
        srs = word["srs_data"]
        old_interval = srs.get("interval_days", 1) or 1
        ease = srs.get("ease_factor", self.starting_ease)

        if rating == "again":
            # Back to learning
            srs["state"] = "learning"
            srs["step_index"] = 0
            srs["lapses"] = srs.get("lapses", 0) + 1
            srs["ease_factor"] = max(self.min_ease_factor, ease - 0.2)
            srs["interval_days"] = 1
            due = now + timedelta(minutes=self.learning_steps_minutes[0])
            srs["due_date"] = due.isoformat()

        elif rating == "hard":
            srs["ease_factor"] = max(self.min_ease_factor, ease - 0.15)
            new_interval = old_interval * self.hard_interval_multiplier
            new_interval *= self.interval_modifier
            new_interval = max(1.0, new_interval)
            srs["interval_days"] = new_interval
            srs["due_date"] = (now + timedelta(days=new_interval)).isoformat()

        elif rating == "good":
            new_interval = old_interval * ease
            new_interval *= self.interval_modifier
            new_interval = max(1.0, new_interval)
            srs["interval_days"] = new_interval
            srs["due_date"] = (now + timedelta(days=new_interval)).isoformat()

        elif rating == "easy":
            srs["ease_factor"] = min(self.max_ease_factor, ease + 0.15)
            new_interval = old_interval * ease * self.easy_bonus
            new_interval *= self.interval_modifier
            new_interval = max(1.0, new_interval)
            srs["interval_days"] = new_interval
            srs["due_date"] = (now + timedelta(days=new_interval)).isoformat()

    # ==================== LEECH DETECTION ====================

    def _check_leech(self, word: Dict[str, Any]) -> None:
        """Mark a word as a leech if it has failed too many times."""
        srs = word.get("srs_data", {})
        lapses = srs.get("lapses", 0)

        if lapses >= self.leech_threshold and not srs.get("is_leech"):
            srs["is_leech"] = True
            logger.warning(
                f"Leech detected: {word.get('word')} "
                f"({lapses} lapses, action: {self.leech_action})"
            )

    # ==================== HELPERS ====================

    def count_new_remaining(self, words: List[Dict[str, Any]]) -> int:
        """How many new words have never been reviewed."""
        return sum(
            1 for w in words
            if w.get("decision") == "new"
            and w.get("srs_data", {}).get("last_reviewed") is None
        )

    def count_due_now(
        self,
        words: List[Dict[str, Any]],
        now: Optional[datetime] = None,
        include_learning: bool = False,
    ) -> int:
        """
        How many reviews are due right now.

        Args:
            words: Full list of word dicts.
            now: Current time (defaults to datetime.now()).
            include_learning: If True, count learning cards too (they
                are always "due" from the engine's perspective, since
                the frontend handles their within-session spacing).
                Defaults to False so the header's "due" counter
                reflects only review-phase cards.

        Returns:
            Count of due cards.
        """
        if now is None:
            now = datetime.now()
        due = self.get_due_reviews(words, now)
        if not include_learning:
            due = [
                w for w in due
                if w.get("srs_data", {}).get("state") != "learning"
            ]
        return len(due)

    def stats(self, words: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Quick stats for monitoring."""
        now = datetime.now()

        total = len(words)
        new_remaining = self.count_new_remaining(words)
        due_now = self.count_due_now(words, now, include_learning=False)

        state_counts = {"learning": 0, "review": 0, "unknown": 0}
        for w in words:
            srs = w.get("srs_data", {})
            if srs.get("last_reviewed") is None:
                continue
            state = srs.get("state", "unknown")
            state_counts[state] = state_counts.get(state, 0) + 1

        leeches = sum(
            1 for w in words
            if w.get("srs_data", {}).get("is_leech")
        )

        return {
            "total_words": total,
            "new_remaining": new_remaining,
            "due_now": due_now,
            "learning": state_counts.get("learning", 0),
            "review": state_counts.get("review", 0),
            "leeches": leeches,
        }


# ==================== STANDALONE TEST ====================

if __name__ == "__main__":
    import sys
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Make src/ importable
    sys.path.insert(0, ".")

    from file_manager import FileManager

    print("Testing SRSEngine...")
    print()

    fm = FileManager()
    fm.ensure_all_files()

    config = fm.get_config()
    engine = SRSEngine(config)

    working = fm.load_working_data()
    words = working["decisions"]

    print("=== Initial stats ===")
    stats = engine.stats(words)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print()

    print("=== Today's cards ===")
    today = engine.get_today_cards(words)
    print(f"  New cards:     {len(today['new'])}")
    print(f"  Due reviews:   {len(today['reviews'])}")
    print(f"  Total:         {today['total']}")
    print()

    if today["new"]:
        print("=== First 3 new cards ===")
        for w in today["new"][:3]:
            print(f"  rank {w['rank']:>6}  {w['word']:<30}  {w['decision']}")
        print()

        # Test rating the first new card
        print("=== Simulating 'good' rating on first new card ===")
        first = today["new"][0]
        print(f"  Before: {first['srs_data']}")
        engine.rate_card(first, "good")
        print(f"  After:  {first['srs_data']}")
        print()

        print("=== Simulating 'good' again (advance step) ===")
        engine.rate_card(first, "good")
        print(f"  After:  {first['srs_data']}")
        print()

        print("=== Simulating 'good' again (graduate) ===")
        engine.rate_card(first, "good")
        print(f"  After:  {first['srs_data']}")
        print()

    print("=== Final stats ===")
    stats = engine.stats(words)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print()

    print("✅ SRSEngine test complete")
    print()
    print("⚠️  Note: test modified SRS data in-memory only.")
    print("    To persist, save via FileManager.")

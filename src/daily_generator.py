#!/usr/bin/env python3
"""
AInki — Daily Generator
=======================

The orchestrator. Runs once per day to prepare the day's cards.

Responsibilities:
    1. Ensure all files are loaded/initialized (via FileManager)
    2. Handle pause tracking (missed days)
    3. Determine today's cards:
        - 10 new cards (from SRS engine)
        - All due reviews (from SRS engine)
    3.5. Load constructions, pick today's new constructions, build slot map
    4. Select practice words per card (from urgency engine)
    5. Generate one sentence per card via DeepSeek, each carrying exactly one
       construction (new-today or rotation)
    6. Record context exposures for practice words used, record construction
       uses, mark today's new constructions introduced, save everything

Design:
    - Uses FileManager for all I/O
    - Uses SRSEngine for scheduling queries
    - Uses UrgencyEngine for practice word selection
    - Uses SentenceGenerator for AI calls
    - Uses ConstructionEngine for construction selection + state
    - Idempotent: safe to re-run (won't duplicate anything)

Progress reporting
------------------
run() accepts an optional progress_callback(pct, msg) which is called at
each pipeline step. Used by the server to drive the UI progress bar.
"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from file_manager import FileManager
from srs_engine import SRSEngine
from urgency_engine import UrgencyEngine
from sentence_generator import SentenceGenerator
from constructions import ConstructionEngine


logger = logging.getLogger(__name__)


class DailyGenerator:
    """Runs the daily card + sentence generation pipeline."""

    def __init__(self, config_path: str = "config/config.json"):
        """Initialize the generator with all sub-engines."""

        self.fm = FileManager(config_path)
        self.config = self.fm.get_config()

        self.srs = SRSEngine(self.config)
        self.urgency = UrgencyEngine(self.config)
        self.sentences = SentenceGenerator(self.config)
        self.constructions = ConstructionEngine(self.config, self.fm)

        self.words: List[Dict[str, Any]] = []
        self.exposure_data: Dict[str, Any] = {}

        self.today_new_constructions: List[Dict[str, Any]] = []
        self.construction_slot_map: List[Optional[str]] = []

        logger.info("DailyGenerator initialized")

    # ==================== PUBLIC ENTRY POINT ====================

    def run(self, progress_callback=None) -> Dict[str, Any]:
        """
        Execute the full daily pipeline.

        Args:
            progress_callback: Optional callable(pct: float, message: str).

        Returns:
            Summary dict with counts and status.
        """
        def report(pct, msg):
            if progress_callback:
                try:
                    progress_callback(float(pct), str(msg))
                except Exception as e:
                    logger.warning(f"progress_callback failed: {e}")

        started = time.time()
        report(0.02, "Starting...")
        logger.info("=" * 60)
        logger.info(f"AInki daily run — {datetime.now().isoformat()}")
        logger.info("=" * 60)

        # ---------- STEP 1: Load / initialize files ----------
        logger.info("[1/6] Loading files...")
        report(0.05, "Loading files...")
        self.fm.ensure_all_files()
        working = self.fm.load_working_data()
        self.words = working["decisions"]
        self.exposure_data = self.fm.load_exposure_data()
        report(0.10, "Files loaded")

        # ---------- STEP 2: Handle pause / missed days ----------
        logger.info("[2/6] Checking pause status...")
        pause = self.fm.load_pause_data()
        self._handle_pause(pause)
        report(0.20, "Pause check done")

        # ---------- STEP 3: Determine today's cards ----------
        logger.info("[3/6] Selecting today's cards...")
        today = self.srs.get_today_cards(self.words)
        new_cards = today["new"]
        review_cards = today["reviews"]

        logger.info(f"      New cards:    {len(new_cards)}")
        logger.info(f"      Review cards: {len(review_cards)}")

        all_cards = new_cards + review_cards
        report(0.30, f"Selected {len(new_cards)} new + {len(review_cards)} review cards")

        # ---------- STEP 3.5: Construction layer ----------
        logger.info("[3.5/6] Preparing construction layer...")
        self.constructions.load()
        self.constructions.begin_run()

        self.today_new_constructions = self.constructions.pick_today_new()
        today_new_ids = [str(c["id"]) for c in self.today_new_constructions]

        if self.today_new_constructions:
            for c in self.today_new_constructions:
                logger.info(
                    f"      New construction: {c.get('id'):>10}  "
                    f"{c.get('word')}  ({self.constructions.gloss_of(c)[:50]})"
                )
        else:
            logger.info("      No new constructions available (pool exhausted)")

        self.construction_slot_map = self.constructions.build_slot_map(
            total_sentences=len(all_cards),
            today_new=self.today_new_constructions,
        )
        n_new_slots = sum(1 for s in self.construction_slot_map if s)
        n_rotation_slots = len(self.construction_slot_map) - n_new_slots
        logger.info(
            f"      Slot map: {n_new_slots} new-construction slots, "
            f"{n_rotation_slots} rotation slots"
        )
        report(0.40, f"Constructions ready ({n_new_slots} new slots)")

        # ---------- STEP 4: Select practice words ----------
        logger.info("[4/6] Selecting practice words...")

        words_per_card = self.config.get("sentence_settings", {}).get(
            "practice_words_per_sentence", 10
        )
        needed_for_generation = len(all_cards) * words_per_card

        practice_pool = self.urgency.select_practice_words(
            words=self.words,
            exposure_data=self.exposure_data,
            count=needed_for_generation,
        )
        logger.info(f"      Selected {len(practice_pool)} practice words "
                    f"(needed {needed_for_generation})")
        report(0.50, f"Selected {len(practice_pool)} practice words")

        # ---------- STEP 5: Generate sentences for all cards ----------
        logger.info("[5/6] Generating sentences for all cards...")
        generated = 0
        failed = 0
        constructions_used = 0
        constructions_fit_failed = 0

        new_ranks = {w.get("rank") for w in new_cards}

        total_cards = max(1, len(all_cards))
        for i, card in enumerate(all_cards):
            pct = 0.55 + 0.40 * (i / total_cards)
            report(pct, f"Generating sentences ({i+1}/{len(all_cards)})")

            start = i * words_per_card
            card_practice = practice_pool[start:start + words_per_card]

            if len(card_practice) < 1:
                logger.warning(f"No practice words left for '{card['word']}', skipping")
                failed += 1
                continue

            is_review = card.get("rank") not in new_ranks

            sentence, construction_rec = self._generate_with_construction_fallback(
                card=card,
                practice_words=card_practice,
                is_review=is_review,
                sentence_index=i,
            )

            if sentence:
                generated += 1
                self._store_sentence(card, sentence, card_practice, construction_rec)
                self._record_practice_exposures(card_practice, sentence)

                if construction_rec is not None:
                    self.constructions.record_use(str(construction_rec["id"]))
                    constructions_used += 1
            else:
                failed += 1

        logger.info(f"      ✅ Generated: {generated}")
        if failed:
            logger.info(f"      ❌ Failed:    {failed}")
        logger.info(f"      🏗️  Constructions used: {constructions_used}")

        # ---------- STEP 5.5: Construction end-of-run ----------
        logger.info("[5.5/6] Finalizing constructions...")
        constr_summary = self.constructions.end_run()
        logger.info(
            f"      Introduced today: {constr_summary['introduced']} "
            f"(total records: {constr_summary['total_records']}, "
            f"used this run: {constr_summary['recent_used']})"
        )
        report(0.97, "Finalizing constructions...")

        # ---------- STEP 6: Save everything ----------
        logger.info("[6/6] Saving files...")
        self._finalize(pause)
        report(1.0, "Done")

        elapsed = time.time() - started
        summary = {
            "timestamp": datetime.now().isoformat(),
            "new_cards": len(new_cards),
            "review_cards": len(review_cards),
            "sentences_generated": generated,
            "sentences_failed": failed,
            "constructions_introduced": constr_summary["introduced"],
            "constructions_used": constructions_used,
            "phase": self.exposure_data.get("phase", "random"),
            "unexposed_remaining": len(self.exposure_data.get("unexposed", [])),
            "elapsed_seconds": round(elapsed, 1),
        }

        logger.info("=" * 60)
        logger.info(f"✅ Done in {elapsed:.1f}s")
        logger.info("=" * 60)

        return summary

    # ==================== PAUSE HANDLING ====================

    def _handle_pause(self, pause: Dict[str, Any]) -> None:
        """Detect missed days and shift the entire schedule forward."""
        if not self.config.get("pause_settings", {}).get("enabled", True):
            return

        last_review_str = pause.get("last_review_date")
        if not last_review_str:
            return

        try:
            last_review = datetime.fromisoformat(last_review_str)
        except (ValueError, TypeError):
            return

        days_since = (datetime.now().date() - last_review.date()).days

        if days_since > 1:
            missed = days_since - 1
            logger.info(f"      ⏸️  Pausing: shifting all dates forward by {missed} day(s)")

            self._shift_all_dates(missed, pause)

            pause["days_behind"] = pause.get("days_behind", 0) + missed
            pause["total_gap_days"] = pause.get("total_gap_days", 0) + missed

            logger.info(
                f"      ✅ Schedule shifted. "
                f"Cumulative gap: {pause['total_gap_days']} day(s)"
            )

        pause["last_review_date"] = datetime.now().isoformat()

    def _shift_all_dates(self, gap_days: int, pause: Dict[str, Any]) -> None:
        """Push every card's SRS dates forward by N days."""
        from datetime import timedelta

        shifted_cards = 0
        for word in self.words:
            srs = word.get("srs_data", {})

            last = srs.get("last_reviewed")
            if last:
                try:
                    srs["last_reviewed"] = (
                        datetime.fromisoformat(last) + timedelta(days=gap_days)
                    ).isoformat()
                except (ValueError, TypeError):
                    pass

            due = srs.get("due_date")
            if due:
                try:
                    srs["due_date"] = (
                        datetime.fromisoformat(due) + timedelta(days=gap_days)
                    ).isoformat()
                    shifted_cards += 1
                except (ValueError, TypeError):
                    pass

        for item in pause.get("review_queue", []):
            sched = item.get("scheduled_date")
            if sched:
                try:
                    item["scheduled_date"] = (
                        datetime.fromisoformat(sched) + timedelta(days=gap_days)
                    ).isoformat()
                except (ValueError, TypeError):
                    pass

        logger.info(f"         → {shifted_cards} cards shifted")

    # ==================== SENTENCE GENERATION ====================

    def _generate_for_card(
        self,
        card: Dict[str, Any],
        practice_words: List[str],
        is_review: bool = False,
        construction: Optional[str] = None,
        construction_gloss: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Call DeepSeek to generate a single sentence for one card."""
        word = card.get("word", "")
        translation = (
            card.get("english")
            or card.get("translation")
            or card.get("meaning")
            or "unknown"
        )
        level = self.config.get("sentence_settings", {}).get("cefr_level", "C1")

        tag = "review" if is_review else "new"
        constr_tag = f"  [+ {construction}]" if construction else ""
        logger.info(
            f"      → [{tag}] {word}{constr_tag}  "
            f"(context: {', '.join(practice_words)})"
        )

        try:
            result = self.sentences.generate_sentence(
                target_word=word,
                translation=translation,
                practice_words=practice_words,
                cefr_level=level,
                is_review=is_review,
                construction=construction,
                construction_gloss=construction_gloss,
            )
        except Exception as e:
            logger.error(f"      Exception during generation: {e}")
            return None

        if result and not result.get("fit_failure"):
            snippet = result["russian"][:60]
            logger.info(f"        ✅ {snippet}...")
        elif result and result.get("fit_failure"):
            logger.info(f"        ⚠️  fit_failure: {result.get('reason', '')}")

        return result

    def _generate_with_construction_fallback(
        self,
        card: Dict[str, Any],
        practice_words: List[str],
        is_review: bool,
        sentence_index: int,
    ) -> tuple:
        """Generate one sentence for this card, applying the construction
        fallback chain if the model signals fit_failure."""
        slot = (
            self.construction_slot_map[sentence_index]
            if sentence_index < len(self.construction_slot_map)
            else None
        )

        primary = None
        if slot is not None:
            primary = self.constructions.by_id(slot)
        if primary is None:
            primary = self.constructions.sample_rotation()

        if primary is not None:
            rec = primary
            result = self._generate_for_card(
                card, practice_words, is_review=is_review,
                construction=rec.get("word"),
                construction_gloss=self.constructions.gloss_of(rec),
            )

            if result and not result.get("fit_failure"):
                return result, rec

            if result and result.get("fit_failure"):
                self.constructions.record_fit_failure(
                    str(rec["id"]),
                    result.get("reason", "unknown"),
                    target_word=card.get("word"),
                    sentence_index=sentence_index,
                )
                self.constructions.record_attempt(
                    str(rec["id"]), success=False
                )

        fallback = None
        if slot is not None and len(self.today_new_constructions) > 1:
            for c in self.today_new_constructions:
                if str(c["id"]) != str(slot):
                    fallback = c
                    break

        if fallback is None:
            fallback = self.constructions.sample_rotation()

        if fallback is not None:
            result = self._generate_for_card(
                card, practice_words, is_review=is_review,
                construction=fallback.get("word"),
                construction_gloss=self.constructions.gloss_of(fallback),
            )
            if result and not result.get("fit_failure"):
                return result, fallback
            if result and result.get("fit_failure"):
                self.constructions.record_fit_failure(
                    str(fallback["id"]),
                    result.get("reason", "unknown"),
                    target_word=card.get("word"),
                    sentence_index=sentence_index,
                )
                self.constructions.record_attempt(
                    str(fallback["id"]), success=False
                )

        result = self._generate_for_card(
            card, practice_words, is_review=is_review,
            construction=None,
            construction_gloss=None,
        )
        if result and not result.get("fit_failure"):
            return result, None

        return None, None

    # ==================== STORAGE ====================

    def _store_sentence(
        self,
        card: Dict[str, Any],
        sentence: Dict[str, Any],
        practice_words: List[str],
        construction_rec: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append the generated sentence to the card's sentence list."""
        entry = {
            "generated": datetime.now().isoformat(),
            "level": self.config.get("sentence_settings", {}).get("cefr_level", "C1"),
            "russian": sentence.get("russian", ""),
            "english": sentence.get("english", ""),
            "practice_words_used": sentence.get("practice_words_used", practice_words),
        }

        if construction_rec is not None:
            entry["construction_id"] = str(construction_rec.get("id"))
            entry["construction"] = construction_rec.get("word")
            entry["construction_instance"] = sentence.get("construction_instance")

        sentences = card.setdefault("sentences", [])
        sentences.append(entry)

        max_sentences = self.config.get("sentence_settings", {}).get(
            "max_sentences_per_word", 10
        )
        if len(sentences) > max_sentences:
            card["sentences"] = sentences[-max_sentences:]

    def _record_practice_exposures(
        self,
        practice_words: List[str],
        sentence: Dict[str, Any],
    ) -> None:
        """Record that each practice word was used as context."""
        used = sentence.get("practice_words_used") or practice_words

        for word_text in used:
            word_obj = next(
                (w for w in self.words if w.get("word") == word_text),
                None,
            )
            if not word_obj:
                continue

            self.urgency.record_context_exposure(
                word=word_obj,
                sentence_data=sentence,
                exposure_data=self.exposure_data,
            )

    # ==================== FINALIZATION ====================

    def _finalize(self, pause: Dict[str, Any]) -> None:
        """Save all modified data structures back to disk."""
        working = {
            "decisions": self.words,
            "total": len(self.words),
        }
        self.fm.save_working_data(working)
        self.fm.save_exposure_data(self.exposure_data)
        self.fm.save_pause_data(pause)

        logger.info("      💾 All files saved")


# ==================== ENTRY POINT ====================

def main() -> int:
    """Run the daily generator. Returns exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        generator = DailyGenerator()
        summary = generator.run()

        print()
        print("=" * 60)
        print("  AInki — Daily Summary")
        print("=" * 60)
        print(f"  Timestamp:                {summary['timestamp']}")
        print(f"  New cards:                {summary['new_cards']}")
        print(f"  Review cards:             {summary['review_cards']}")
        print(f"  Sentences created:        {summary['sentences_generated']}")
        print(f"  Failed:                   {summary['sentences_failed']}")
        print(f"  Constructions introduced: {summary['constructions_introduced']}")
        print(f"  Constructions used:       {summary['constructions_used']}")
        print(f"  Phase:                    {summary['phase']}")
        print(f"  Unexposed left:           {summary['unexposed_remaining']}")
        print(f"  Elapsed:                  {summary['elapsed_seconds']}s")
        print("=" * 60)
        print()
        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        return 130
    except Exception as e:
        logging.exception("Fatal error")
        print(f"\n❌ Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

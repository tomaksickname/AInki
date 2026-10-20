#!/usr/bin/env python3
"""
AInki — Construction Engine
===========================

Selection and state for the construction layer.

A "construction" is a fixed multi-word syntactic frame (вместо того чтобы,
в течение, чем...тем...). 1215 of them, split into:

    * new       — 583 never-introduced constructions
    * practice  — 632 constructions that are always in rotation

State model
-----------
Derived from urgency_data.introduced_date:

    introduced_date is None    -> unused (not yet introduced)
    introduced_date == today   -> new today
    introduced_date  < today   -> rotation

There is no `usage_stage` field and no SRS half. Constructions are input-only.

New-today pool
--------------
`pick_today_new` prefers records with `decision == "new"`. Once that block
is exhausted (~290 days in at 2/day), it falls back to any un-introduced
record regardless of `decision`. This keeps day-1..N aligned with the
hand-curated `new` set, and degrades gracefully afterwards.

Two record shapes coexist in the master file
--------------------------------------------
    Shape A (hand-curated, id like "c300_006"):
        fields: id, word, decision, translation, definition, examples
    Shape B (Constructicon, id like "4", bare-integer-as-string):
        fields: id, word, decision, cefr, translation, definition, examples,
                and optionally usage_label, anchor_words, common_fillers,
                sem_type, sem_subtype

The engine does not care which shape a record came from. Optional fields are
read defensively via .get(). Only id, word, and decision are assumed present
(the migration validates those).

Gloss helper
------------
`gloss_of` returns a short human-readable string for prompting:
    translation  -> if present (preferred; usually short)
    definition   -> if translation absent (truncated to config.max)
    word         -> if neither present

Metavariable patterns
---------------------
Some Shape B `word` values are patterns, e.g.
    "(а) при чём здесь/тут Cop NP-Nom?"
When the LLM sees one of these, it is expected to *realize* the pattern with
concrete Russian and report that realization as `construction_instance`. The
engine therefore uses LOOSE validation on the instance: it must be a non-empty
substring of the sentence, but need not equal `word`. The `construction_used`
field is still required to equal `word` exactly.

Usage
-----
    engine = ConstructionEngine(config, fm)
    engine.load()
    engine.begin_run()

    new_today = engine.pick_today_new()
    slot_map  = engine.build_slot_map(total_sentences, new_today)

    # inside the sentence loop:
    rec = engine.by_id(slot_id) if slot_id else engine.sample_rotation()
    gloss = engine.gloss_of(rec)
    # ... call sentence generator ...
    engine.record_use(rec["id"])                       # on success
    engine.record_fit_failure(rec["id"], reason, ...)  # on fit_failure

    engine.end_run()  # marks new today introduced + saves
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_TODAY_FMT = "%Y-%m-%d"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _today_str() -> str:
    return date.today().strftime(_TODAY_FMT)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, _TODAY_FMT).date()
    except (ValueError, TypeError):
        return None


def _days_since(last_used: Optional[str], today: date) -> int:
    """
    Days since last use. If never used, treat as a large finite value so the
    priority formula stays well-defined and never-used constructions get
    aggressively sampled on first rotation.
    """
    d = _parse_date(last_used)
    if d is None:
        return 3650
    return max(0, (today - d).days)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ConstructionEngine:
    """Selection + state for the construction layer."""

    def __init__(self, config: Dict[str, Any], file_manager: Any):
        """
        Args:
            config:         Full config dict (from FileManager.get_config()).
            file_manager:   FileManager instance (used for all disk I/O).
        """
        self.config = config
        self.fm = file_manager

        cs = config.get("construction_settings", {}) or {}
        self.enabled = bool(cs.get("enabled", True))
        self.new_per_day = int(cs.get("new_per_day", 2))
        self.slots_per_new = int(cs.get("slots_per_new_construction", 10))
        self.alpha = float(cs.get("rotation_alpha", 1.0))
        self.anti_cluster_window = int(cs.get("anti_cluster_window", 10))
        self.jitter_min = int(cs.get("slot_jitter_min", 3))
        self.jitter_max = int(cs.get("slot_jitter_max", 5))
        self.gloss_max = int(cs.get("gloss_max_chars", 200))

        # Master list (raw records, mutated in place).
        self.records: List[Dict[str, Any]] = []
        self._by_id: Dict[str, Dict[str, Any]] = {}

        # Per-run state, reset at the start of each daily run.
        self.today_new_ids: List[str] = []
        self.recent_ids: List[str] = []

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load the master file and index it by id."""
        self.records = self.fm.load_constructions()
        self._by_id = {str(r.get("id")): r for r in self.records}
        logger.info(f"ConstructionEngine loaded {len(self.records)} records")

    def save(self) -> None:
        """Persist the master file."""
        self.fm.save_constructions(self.records)

    def by_id(self, construction_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(str(construction_id))

    # ------------------------------------------------------------------
    # Today's new constructions
    # ------------------------------------------------------------------

    def pick_today_new(self, n: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Return up to `n` un-introduced constructions in file order.

        Eligibility, in order of preference:
            1. `decision == "new"` AND `introduced_date` is null.
            2. Any record with `introduced_date` null (fallback, once the
               `new` block is exhausted — typically ~290 days in).

        A record is 'un-introduced' when urgency_data.introduced_date is falsy.

        Side effect: sets self.today_new_ids so downstream calls (slot map,
        rotation exclusion) know which ids to treat as "new today".
        """
        n = self.new_per_day if n is None else int(n)

        # Pass 1: prefer decision == "new"
        out: List[Dict[str, Any]] = []
        for rec in self.records:
            if rec.get("decision") != "new":
                continue
            ud = rec.get("urgency_data") or {}
            if not ud.get("introduced_date"):
                out.append(rec)
                if len(out) >= n:
                    break

        # Pass 2: fallback to any un-introduced record if pass 1 came up short.
        if len(out) < n:
            already = {str(r.get("id")) for r in out}
            for rec in self.records:
                if str(rec.get("id")) in already:
                    continue
                if rec.get("decision") == "new":
                    continue  # already considered (and rejected) in pass 1
                ud = rec.get("urgency_data") or {}
                if not ud.get("introduced_date"):
                    out.append(rec)
                    if len(out) >= n:
                        break

        self.today_new_ids = [str(r["id"]) for r in out]
        if not out:
            logger.info("ConstructionEngine: no un-introduced constructions left")
        elif out[0].get("decision") != "new":
            logger.warning(
                "ConstructionEngine: 'new' pool exhausted; falling back to "
                "un-introduced practice records"
            )
        return out

    def mark_introduced(
        self,
        construction_ids: Iterable[str],
        when: Optional[str] = None,
    ) -> int:
        """
        Set urgency_data.introduced_date = `when` (default today) for given ids.
        Only sets it if it was previously falsy. Returns count updated.

        Mutates in place. Caller is responsible for calling save() afterwards
        (or use end_run(), which does both).
        """
        when = when or _today_str()
        wanted = {str(cid) for cid in construction_ids}
        updated = 0
        for rec in self.records:
            if str(rec.get("id")) in wanted:
                ud = rec.setdefault("urgency_data", {})
                if not ud.get("introduced_date"):
                    ud["introduced_date"] = when
                    updated += 1
        return updated

    # ------------------------------------------------------------------
    # Slot map (interleaving)
    # ------------------------------------------------------------------

    def build_slot_map(
        self,
        total_sentences: int,
        today_new: List[Dict[str, Any]],
        rng: Optional[random.Random] = None,
    ) -> List[Optional[str]]:
        """
        Build a list of length `total_sentences`. Each element is:
            * a construction id from today's new set (a "new slot"), or
            * None (meaning: caller should sample from rotation).

        Strategy
        --------
        Anchor positions are distributed across the day. The base spacing is
        total_sentences / target_slots; each subsequent anchor is placed
        base_step + jitter sentences later, where jitter is drawn from
        [jitter_min, jitter_max]. Anchors are then alternated between today's
        new constructions.

        This yields interleaved slots rather than a block at the start. With
        the defaults (2 new, 10 slots each, ~80 sentences), you get ~20 new
        slots spread across ~80 sentences, alternating between the two ids.
        """
        rng = rng or random.Random()
        slots: List[Optional[str]] = [None] * total_sentences

        if not today_new or total_sentences <= 0 or not self.enabled:
            return slots

        new_ids = [str(r["id"]) for r in today_new]
        target_slots = min(total_sentences, self.slots_per_new * len(new_ids))
        if target_slots <= 0:
            return slots

        # Base step: average spacing between anchors.
        base_step = max(1, total_sentences // max(1, target_slots))

        anchors: List[int] = []
        cursor = rng.randint(0, max(0, base_step - 1))
        while len(anchors) < target_slots and cursor < total_sentences:
            anchors.append(cursor)
            jitter = rng.randint(self.jitter_min, self.jitter_max)
            # Blend base_step with the jitter band so we honour the config.
            step = max(1, (base_step + jitter) // 2)
            cursor += step

        # Fill remaining slots evenly if we ran out of room.
        if len(anchors) < target_slots:
            used = set(anchors)
            for pos in range(total_sentences):
                if pos not in used:
                    anchors.append(pos)
                    if len(anchors) >= target_slots:
                        break

        anchors = sorted(set(a for a in anchors if 0 <= a < total_sentences))

        # Alternate ids across anchors.
        for i, pos in enumerate(anchors):
            slots[pos] = new_ids[i % len(new_ids)]

        return slots

    # ------------------------------------------------------------------
    # Rotation sampling
    # ------------------------------------------------------------------

    def _rotation_pool(self, today: date) -> List[Dict[str, Any]]:
        """
        All records in rotation today: decision == 'practice', OR
        introduced_date < today (previously introduced). Excludes the
        currently-new set (those are handled via slot map).
        """
        today_s = today.strftime(_TODAY_FMT)
        new_set = set(self.today_new_ids)
        pool: List[Dict[str, Any]] = []
        for rec in self.records:
            rid = str(rec.get("id"))
            if rid in new_set:
                continue
            ud = rec.get("urgency_data") or {}
            if rec.get("decision") == "practice":
                pool.append(rec)
            else:
                intro = ud.get("introduced_date")
                if intro and intro < today_s:
                    pool.append(rec)
        return pool

    def _priority(self, rec: Dict[str, Any], today: date) -> float:
        ud = rec.get("urgency_data") or {}
        days = _days_since(ud.get("last_used_in_input"), today)
        jitter = random.uniform(0.5, 1.5)
        return ((days + 1) ** self.alpha) * jitter

    def sample_rotation(
        self,
        recent_ids: Optional[List[str]] = None,
        today: Optional[date] = None,
        rng: Optional[random.Random] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Pick one rotation construction.

        Priority = (days_since_last_use + 1) ** alpha * U(0.5, 1.5).
        Anti-clustering: exclude ids in the last `anti_cluster_window` slots
        of `recent_ids`. If that empties the pool, fall back to the full pool.

        `recent_ids` defaults to self.recent_ids (maintained by record_use).
        Returns None if the pool is empty (e.g. all constructions were
        introduced today and none are in rotation yet).
        """
        today = today or date.today()
        rng = rng or random.Random()
        recent_ids = recent_ids if recent_ids is not None else self.recent_ids

        pool = self._rotation_pool(today)
        if not pool:
            return None

        blocked = set(str(cid) for cid in recent_ids[-self.anti_cluster_window:])
        filtered = [r for r in pool if str(r.get("id")) not in blocked]
        if not filtered:
            filtered = pool

        weights = [self._priority(r, today) for r in filtered]
        total = sum(weights)
        if total <= 0:
            return rng.choice(filtered)
        pick = rng.uniform(0, total)
        acc = 0.0
        for rec, w in zip(filtered, weights):
            acc += w
            if acc >= pick:
                return rec
        return filtered[-1]

    # ------------------------------------------------------------------
    # Recording outcomes
    # ------------------------------------------------------------------

    def record_use(
        self,
        construction_id: str,
        when: Optional[str] = None,
    ) -> bool:
        """
        Mark a construction as successfully used today. Updates
        last_used_in_input, last_seen, total_exposures, exposure_history.
        Also appends to self.recent_ids for anti-clustering.
        """
        when = when or _today_str()
        rec = self.by_id(construction_id)
        if rec is None:
            return False
        ud = rec.setdefault("urgency_data", {})
        ud["last_used_in_input"] = when
        ud["last_seen"] = when
        ud["total_exposures"] = int(ud.get("total_exposures") or 0) + 1
        hist = ud.setdefault("exposure_history", [])
        if not isinstance(hist, list):
            hist = []
            ud["exposure_history"] = hist
        hist.append(when)
        self.recent_ids.append(str(construction_id))
        return True

    def record_attempt(
        self,
        construction_id: str,
        *,
        success: bool,
        when: Optional[str] = None,
    ) -> bool:
        """
        Record an attempt that did NOT necessarily succeed. On success,
        delegates to record_use. On failure, only updates last_seen (so the
        record reflects that it was tried, without bumping exposures).
        """
        if success:
            return self.record_use(construction_id, when=when)
        when = when or _today_str()
        rec = self.by_id(construction_id)
        if rec is None:
            return False
        ud = rec.setdefault("urgency_data", {})
        ud["last_seen"] = when
        return True

    def record_fit_failure(
        self,
        construction_id: str,
        reason: str,
        *,
        target_word: Optional[str] = None,
        sentence_index: Optional[int] = None,
        when: Optional[str] = None,
    ) -> None:
        """
        Append a fit-failure event to the fit log. The master file is not
        touched. Loads the log, appends, saves atomically.

        The fit log is purely diagnostic. If it is corrupt, FileManager
        resets it to [] and the current event becomes the first entry.
        """
        when = when or _today_str()
        entry = {
            "date": when,
            "construction_id": str(construction_id),
            "reason": str(reason) if reason is not None else "",
            "target_word": target_word,
            "sentence_index": sentence_index,
        }
        log = self.fm.load_construction_fit_log()
        log.append(entry)
        self.fm.save_construction_fit_log(log)

    # ------------------------------------------------------------------
    # Gloss helper
    # ------------------------------------------------------------------

    def gloss_of(self, rec: Dict[str, Any]) -> str:
        """
        Short human-readable string for prompting.

        Order: translation -> definition -> word.
        Truncated to config.gloss_max_chars with an ellipsis if needed.
        """
        text = (
            rec.get("translation")
            or rec.get("definition")
            or rec.get("word")
            or ""
        )
        text = str(text).strip()
        if len(text) > self.gloss_max:
            text = text[: self.gloss_max - 1].rstrip() + "…"
        return text

    # ------------------------------------------------------------------
    # Per-run lifecycle
    # ------------------------------------------------------------------

    def begin_run(self) -> None:
        """
        Reset per-run state. Call once at the top of a daily run, after
        load(), before pick_today_new().
        """
        self.recent_ids = []
        self.today_new_ids = []

    def end_run(self, when: Optional[str] = None) -> Dict[str, Any]:
        """
        Mark today's new constructions as introduced, save the master file,
        and return a small summary for logging.

        Safe to call when today_new_ids is empty (e.g. all constructions
        already introduced) — it still saves the master file, which is
        useful because record_use() mutated it during the run.
        """
        when = when or _today_str()
        marked = self.mark_introduced(self.today_new_ids, when=when)
        self.save()
        return {
            "date": when,
            "introduced": marked,
            "total_records": len(self.records),
            "recent_used": len(self.recent_ids),
        }


# ==================== STANDALONE TEST ====================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    from file_manager import FileManager

    print("Testing ConstructionEngine...")
    print()

    fm = FileManager()
    engine = ConstructionEngine(fm.get_config(), fm)
    engine.load()
    engine.begin_run()

    print("=== Master file ===")
    print(f"  Records loaded: {len(engine.records)}")
    print(f"  Indexed by id:  {len(engine._by_id)}")
    print()

    print("=== Today's new ===")
    today_new = engine.pick_today_new()
    for rec in today_new:
        print(f"  {rec['id']:>10}  {rec['word']:<30}  decision={rec['decision']}")
        print(f"             gloss: {engine.gloss_of(rec)[:70]}")
    print()

    print("=== Slot map (80 sentences) ===")
    slot_map = engine.build_slot_map(80, today_new)
    filled = [(i, s) for i, s in enumerate(slot_map) if s]
    print(f"  New-slot positions: {[i for i, _ in filled]}")
    print(f"  Total new slots:    {len(filled)}")
    print()

    print("=== Rotation samples (5) ===")
    for _ in range(5):
        rec = engine.sample_rotation()
        if rec:
            print(f"  {rec['id']:>10}  {rec['word']}")
        else:
            print("  (no rotation pool — all constructions are new today?)")
    print()

    print("=== Fit log ===")
    print(f"  Entries: {len(fm.load_construction_fit_log())}")
    print()

    print("✅ ConstructionEngine test complete")

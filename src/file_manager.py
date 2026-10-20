#!/usr/bin/env python3
"""
AInki — File Manager
====================

Centralized read/write operations for all data files.

Responsibilities:
    - Load config.json
    - Load decisions.json (READ-ONLY original)
    - Load/initialize vocabulary_data.json (working copy)
    - Load/initialize exposure_data.json (urgency tracking)
    - Load/initialize pause_data.json (review queue)
    - Load/initialize constructions_master.json (construction layer)
    - Load/append construction_fit_log.json (fit-failure audit)
    - Save all of the above atomically
    - Handle empty/missing files gracefully
    - Provide backup of original file

Design:
    - Idempotent: safe to call multiple times
    - Auto-initializes empty files on first run
    - Never modifies decisions.json (read-only)
    - Uses atomic writes to prevent corruption
"""

import json
import shutil
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


class FileManager:
    """Handles all file I/O for AInki."""

    # ==================== INITIALIZATION ====================

    def __init__(self, config_path: str = "config/config.json"):
        """
        Initialize FileManager.

        Args:
            config_path: Path to config.json (relative to project root)
        """
        self.project_root = Path(config_path).resolve().parent.parent
        self.config_path = self.project_root / "config" / "config.json"

        # Load config
        self.config = self._load_config()

        # Resolve all file paths from config
        paths = self.config.get("file_paths", {})
        self.data_dir = self.project_root / paths.get("data_dir", "data/")
        self.original_file = self.project_root / paths.get("original_file", "data/decisions.json")
        self.working_file = self.project_root / paths.get("working_file", "data/vocabulary_data.json")
        self.exposure_file = self.project_root / paths.get("exposure_file", "data/exposure_data.json")
        self.pause_file = self.project_root / paths.get("pause_file", "data/pause_data.json")
        self.backup_file = self.project_root / paths.get("backup_file", "data/backup_decisions.json")
        self.log_file = self.project_root / paths.get("log_file", "logs/daily_generator.log")
        self.constructions_file = self.project_root / paths.get(
            "constructions_file", "data/constructions_master.json"
        )
        self.construction_fit_log_file = self.project_root / paths.get(
            "construction_fit_log_file", "data/construction_fit_log.json"
        )

        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"FileManager initialized")
        logger.info(f"  Project root: {self.project_root}")
        logger.info(f"  Data dir:     {self.data_dir}")

    # ==================== CONFIG ====================

    def _load_config(self) -> Dict[str, Any]:
        """Load and validate config.json."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Basic validation
        required_keys = ["file_paths", "api_settings", "srs_settings"]
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Missing required config key: {key}")

        return config

    def get_config(self) -> Dict[str, Any]:
        """Return the loaded config."""
        return self.config

    # ==================== GENERIC JSON I/O ====================

    @staticmethod
    def _load_json(path: Path) -> Optional[Any]:
        """Load JSON file. Returns None if file missing or empty."""
        if not path.exists():
            return None

        if path.stat().st_size == 0:
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Corrupt JSON in {path}: {e}")
            raise

    @staticmethod
    def _save_json(path: Path, data: Any) -> None:
        """
        Save JSON atomically (write to temp, then rename).
        Prevents corruption if interrupted mid-write.
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file in same directory (required for atomic rename)
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, path)
        except Exception:
            # Clean up temp file on error
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    # ==================== ORIGINAL DECISIONS (READ-ONLY) ====================

    def load_original_decisions(self) -> Dict[str, Any]:
        """
        Load decisions.json (READ-ONLY original).

        Returns:
            {"decisions": [...], "total": N}
        """
        data = self._load_json(self.original_file)

        if data is None:
            raise FileNotFoundError(
                f"Original decisions file is missing or empty: {self.original_file}"
            )

        if "decisions" not in data:
            raise ValueError(
                f"Invalid structure in {self.original_file}: "
                f"expected 'decisions' key, got {list(data.keys())}"
            )

        if not isinstance(data["decisions"], list):
            raise ValueError(
                f"Invalid structure in {self.original_file}: "
                f"'decisions' must be a list"
            )

        return data

    def get_original_words(self) -> List[Dict[str, Any]]:
        """Convenience: return just the list of original words."""
        return self.load_original_decisions()["decisions"]

    def backup_original(self) -> None:
        """Create a backup of decisions.json (only if backup doesn't exist)."""
        if self.backup_file.exists():
            logger.debug(f"Backup already exists: {self.backup_file}")
            return

        if not self.original_file.exists():
            logger.warning(f"Cannot backup: {self.original_file} does not exist")
            return

        shutil.copy2(self.original_file, self.backup_file)
        logger.info(f"✅ Backup created: {self.backup_file}")

    # ==================== WORKING DATA (vocabulary_data.json) ====================

    def load_working_data(self) -> Dict[str, Any]:
        """
        Load vocabulary_data.json.
        Auto-initializes from decisions.json if empty/missing.
        """
        data = self._load_json(self.working_file)

        if data is None:
            logger.info("Working file empty/missing — initializing from decisions.json")
            data = self._initialize_working_data()
            self.save_working_data(data)

        return data

    def save_working_data(self, data: Dict[str, Any]) -> None:
        """Save vocabulary_data.json."""
        # Update metadata timestamp
        if "metadata" not in data:
            data["metadata"] = {}
        data["metadata"]["last_updated"] = datetime.now().isoformat()
        data["metadata"]["total_words"] = len(data.get("decisions", []))

        self._save_json(self.working_file, data)
        logger.debug(f"Saved working data: {self.working_file}")

    def _initialize_working_data(self) -> Dict[str, Any]:
        """
        Build vocabulary_data.json from decisions.json.

        Enriches each word with:
            - srs_data:     SRS scheduling fields
            - urgency_data: exposure tracking fields
            - sentences:    list of generated sentences
        """
        original = self.load_original_decisions()
        original_words = original["decisions"]

        enriched_words = []
        for word in original_words:
            enriched = self._enrich_word(word)
            enriched_words.append(enriched)

        now = datetime.now().isoformat()
        data = {
            "decisions": enriched_words,
            "total": len(enriched_words),
            "metadata": {
                "created": now,
                "last_updated": now,
                "source": str(self.original_file.relative_to(self.project_root)),
                "version": "1.0",
            },
        }

        logger.info(f"Initialized working data: {len(enriched_words)} words")
        return data

    def _enrich_word(self, word: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add SRS/urgency/sentences fields to a raw word from decisions.json.

        Preserves: rank, word, pos, decision, and any other original fields.
        """
        enriched = dict(word)  # copy original fields

        decision = word.get("decision", "new")

        # ---------- SRS data ----------
        enriched["srs_data"] = {
            "created": datetime.now().isoformat(),
            "last_reviewed": None,
            "review_count": 0,
            "interval_days": 1 if decision == "new" else 7,
            "ease_factor": self.config["srs_settings"].get("starting_ease", 2.5),
            "due_date": None,
            "lapses": 0,
            "step_index": 0,
            "state": "learning" if decision == "new" else "review",
            "is_leech": False,
            "introduced_date": None,
        }

        # ---------- Urgency data ----------
        enriched["urgency_data"] = {
            "total_exposures": 0,
            "context_exposures": 0,
            "review_exposures": 0,
            "last_seen": None,
            "exposure_history": [],
        }

        # ---------- Sentences ----------
        enriched["sentences"] = []

        return enriched

    # ==================== EXPOSURE DATA ====================

    def load_exposure_data(self) -> Dict[str, Any]:
        """
        Load exposure_data.json.
        Auto-initializes if empty/missing.
        """
        data = self._load_json(self.exposure_file)

        if data is None:
            logger.info("Exposure file empty/missing — initializing")
            data = self._initialize_exposure_data()
            self.save_exposure_data(data)

        return data

    def save_exposure_data(self, data: Dict[str, Any]) -> None:
        """Save exposure_data.json."""
        self._save_json(self.exposure_file, data)
        logger.debug(f"Saved exposure data: {self.exposure_file}")

    def _initialize_exposure_data(self) -> Dict[str, Any]:
        """
        Initialize exposure tracking.

        Structure:
            {
                "phase": "random" | "urgency",
                "days_running": int,
                "unexposed": [word, ...],   # words not yet used as context
                "exposure_history": {word: {total_exposures, last_seen}},
                "metadata": {...}
            }
        """
        # Build list of all unique practice words
        working = self.load_working_data()
        practice_words = [
            w["word"] for w in working["decisions"]
            if w.get("decision") == "practice"
        ]

        # Dedupe while preserving order
        seen = set()
        unique_practice = []
        for word in practice_words:
            if word not in seen:
                seen.add(word)
                unique_practice.append(word)

        data = {
            "phase": "random",
            "days_running": 0,
            "unexposed": unique_practice,
            "exposure_history": {},
            "metadata": {
                "created": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "total_practice_words": len(unique_practice),
            },
        }

        logger.info(f"Initialized exposure data: {len(unique_practice)} unique practice words")
        return data

    # ==================== PAUSE DATA ====================

    def load_pause_data(self) -> Dict[str, Any]:
        """
        Load pause_data.json.
        Auto-initializes if empty/missing.
        """
        data = self._load_json(self.pause_file)

        if data is None:
            logger.info("Pause file empty/missing — initializing")
            data = self._initialize_pause_data()
            self.save_pause_data(data)

        return data

    def save_pause_data(self, data: Dict[str, Any]) -> None:
        """Save pause_data.json."""
        self._save_json(self.pause_file, data)
        logger.debug(f"Saved pause data: {self.pause_file}")

    def _initialize_pause_data(self) -> Dict[str, Any]:
        """
        Initialize pause tracking.

        Structure:
            {
                "last_review_date": iso,     # last day the user actually reviewed
                "paused_since": iso | null,  # if paused, when the pause started
                "days_behind": int,          # current backlog (usually 0 with pause)
                "total_gap_days": int,       # cumulative days skipped, all-time
                "review_queue": [...],       # deferred cards
                "metadata": {...}
            }
        """
        now = datetime.now().isoformat()
        return {
            "last_review_date": now,
            "paused_since": None,
            "days_behind": 0,
            "total_gap_days": 0,
            "review_queue": [],
            "metadata": {
                "created": now,
                "last_updated": now,
            },
        }

    # ==================== CONSTRUCTIONS ====================

    def load_constructions(self) -> List[Dict[str, Any]]:
        """
        Load data/constructions_master.json.

        Unlike vocabulary_data.json, constructions have no original-vs-working
        split — the master file IS the working file. Auto-initializes to an
        empty list if the file is missing, so callers can run safely before
        migration has been performed.

        Returns a list of construction records. Each record carries an
        `urgency_data` sub-object after migration (see
        scripts/migrate_constructions.py).
        """
        data = self._load_json(self.constructions_file)
        if data is None:
            logger.warning(
                f"Constructions file missing/empty ({self.constructions_file}); "
                f"returning empty list. Run scripts/migrate_constructions.py first."
            )
            return []
        if not isinstance(data, list):
            raise ValueError(
                f"{self.constructions_file}: expected a JSON list at top level, "
                f"got {type(data).__name__}"
            )
        return data

    def save_constructions(self, records: List[Dict[str, Any]]) -> None:
        """Atomic save of the constructions master file."""
        self._save_json(self.constructions_file, records)
        logger.debug(
            f"Saved constructions: {self.constructions_file} ({len(records)} records)"
        )

    def load_construction_fit_log(self) -> List[Dict[str, Any]]:
        """
        Load the append-only fit-failure log.

        Returns [] if the file is missing or empty. A non-list payload is
        treated as corrupt and reset to [] (with a warning) — the fit log is
        purely diagnostic and losing it is preferable to crashing a run.
        """
        data = self._load_json(self.construction_fit_log_file)
        if data is None:
            return []
        if not isinstance(data, list):
            logger.warning(
                f"{self.construction_fit_log_file}: expected a JSON list, got "
                f"{type(data).__name__}; resetting to empty list."
            )
            return []
        return data

    def save_construction_fit_log(self, entries: List[Dict[str, Any]]) -> None:
        """Atomic save of the fit-failure log."""
        self._save_json(self.construction_fit_log_file, entries)
        logger.debug(
            f"Saved fit log: {self.construction_fit_log_file} ({len(entries)} entries)"
        )

    # ==================== CONVENIENCE ====================

    def ensure_all_files(self) -> None:
        """
        Ensure all required files exist and are initialized.
        Call this on startup to guarantee clean state.

        Note: the constructions master file is NOT auto-initialized here.
        It is a migration artifact, not a runtime-created file. Callers that
        need constructions should tolerate an empty list.
        """
        logger.info("Ensuring all files are initialized...")

        # 1. Original must exist
        if not self.original_file.exists():
            raise FileNotFoundError(
                f"Original file missing: {self.original_file}\n"
                f"Please place your decisions.json in {self.data_dir}"
            )

        # 2. Backup original (only if not already backed up)
        self.backup_original()

        # 3. Initialize (or load) working data
        self.load_working_data()

        # 4. Initialize (or load) exposure data
        self.load_exposure_data()

        # 5. Initialize (or load) pause data
        self.load_pause_data()

        logger.info("✅ All files ready")

    def reset_working_data(self) -> None:
        """
        Reset working data (vocabulary_data.json) to fresh state.
        Does NOT touch decisions.json.
        """
        logger.warning("Resetting working data from original...")
        data = self._initialize_working_data()
        self.save_working_data(data)
        logger.info("✅ Working data reset")

    def reset_exposure_data(self) -> None:
        """Reset exposure_data.json to fresh state."""
        logger.warning("Resetting exposure data...")
        data = self._initialize_exposure_data()
        self.save_exposure_data(data)
        logger.info("✅ Exposure data reset")

    def reset_pause_data(self) -> None:
        """Reset pause_data.json to fresh state."""
        logger.warning("Resetting pause data...")
        data = self._initialize_pause_data()
        self.save_pause_data(data)
        logger.info("✅ Pause data reset")

    # ==================== STATS / INFO ====================

    def get_stats(self) -> Dict[str, Any]:
        """Return basic stats about the current state."""
        working = self.load_working_data()
        words = working["decisions"]

        from collections import Counter
        counts = Counter(w.get("decision", "unknown") for w in words)

        return {
            "total": len(words),
            "new": counts.get("new", 0),
            "practice": counts.get("practice", 0),
            "mastered": counts.get("mastered", 0),
            "other": sum(v for k, v in counts.items()
                         if k not in ("new", "practice", "mastered")),
        }


# ==================== STANDALONE TEST ====================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    print("Testing FileManager...")
    print()

    fm = FileManager()

    print("=== Ensuring all files ===")
    fm.ensure_all_files()
    print()

    print("=== Stats ===")
    stats = fm.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print()

    print("=== Working file check ===")
    working = fm.load_working_data()
    print(f"  Total words: {working['total']}")
    print(f"  Metadata: {working['metadata']}")
    print(f"  First word: {working['decisions'][0]}")
    print()

    print("=== Exposure file check ===")
    exposure = fm.load_exposure_data()
    print(f"  Phase: {exposure['phase']}")
    print(f"  Unexposed practice words: {len(exposure['unexposed'])}")
    print(f"  Total practice words: {exposure['metadata']['total_practice_words']}")
    print()

    print("=== Pause file check ===")
    pause = fm.load_pause_data()
    print(f"  Last review: {pause['last_review_date']}")
    print(f"  Days behind: {pause['days_behind']}")
    print(f"  Queue size: {len(pause['review_queue'])}")
    print()

    print("=== Constructions file check ===")
    constructions = fm.load_constructions()
    print(f"  Total constructions: {len(constructions)}")
    if constructions:
        sample = constructions[0]
        print(f"  First id:   {sample.get('id')}")
        print(f"  First word: {sample.get('word')}")
        has_urgency = all("urgency_data" in r for r in constructions)
        print(f"  All records have urgency_data: {has_urgency}")
    print()

    print("=== Fit log check ===")
    fit_log = fm.load_construction_fit_log()
    print(f"  Fit log entries: {len(fit_log)}")
    print()

    print("✅ FileManager test complete")

#!/usr/bin/env python3
"""
AInki — Constructions Migration
===============================

One-time (idempotent) migration that turns the raw constructions list into
the runtime-ready master file used by ConstructionEngine.

Input
-----
    ./constructions_master.json        (project root; pristine original)

Output
------
    data/constructions_master.json     (runtime master; safe to rewrite)
    data/constructions_migration.log   (append-only audit log)

What it does
------------
1. Reads the root file (1215 records in two shapes — hand-curated c300_NNN
   and Constructicon bare-integer ids). No assumptions about field order or
   which optional fields exist on which record.
2. Normalizes each record's `id` to a string.
3. Validates that ids are unique. Aborts on duplicates.
4. Warns (but does not abort) for any record missing a valid `decision`
   value ("new" or "practice").
5. Adds an `urgency_data` sub-object to every record that lacks one:
       introduced_date    : null
       last_used_in_input : null
       total_exposures    : 0
       last_seen          : null
       exposure_history   : []
6. Writes data/constructions_master.json atomically (temp + os.replace).

Preserves
---------
* Every original field, in original order.
* Original records without urgency_data are modified only by appending one key.

Idempotent: re-running on an already-migrated output finds urgency_data in
place and leaves it untouched. It still re-validates and re-reports.

Usage
-----
    python3 scripts/migrate_constructions.py
    python3 scripts/migrate_constructions.py --src ./constructions_master.json \\
                                            --dst data/constructions_master.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_SRC = "constructions_master.json"
DEFAULT_DST = "data/constructions_master.json"
DEFAULT_LOG = "data/constructions_migration.log"

EMPTY_URGENCY: Dict[str, Any] = {
    "introduced_date": None,
    "last_used_in_input": None,
    "total_exposures": 0,
    "last_seen": None,
    "exposure_history": [],
}

VALID_DECISIONS = {"new", "practice"}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str, log_path: Path) -> None:
    print(msg)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate(src: Path, dst: Path, log_path: Path) -> int:
    if not src.exists():
        _log(f"ERROR: source file not found: {src}", log_path)
        return 2

    _log(f"Reading source: {src}", log_path)
    raw = _load_json(src)

    if not isinstance(raw, list):
        _log(f"ERROR: expected a JSON list at top level, got {type(raw).__name__}", log_path)
        return 2

    records: List[Dict[str, Any]] = raw
    _log(f"Records read: {len(records)}", log_path)

    # ---- First pass: validate and gather diagnostics ---------------------
    seen_ids: Dict[str, int] = {}
    duplicates: List[str] = []
    bad_decision: List[Any] = []
    non_string_ids = 0
    c300_count = 0
    int_count = 0
    other_id_count = 0

    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            _log(f"ERROR: record at index {idx} is not an object", log_path)
            return 2
        if "id" not in rec:
            _log(f"ERROR: record at index {idx} has no id", log_path)
            return 2

        raw_id = rec["id"]
        if not isinstance(raw_id, str):
            non_string_ids += 1
        sid = str(raw_id)

        if sid in seen_ids:
            duplicates.append(sid)
        else:
            seen_ids[sid] = idx

        if sid.startswith("c300_"):
            c300_count += 1
        elif sid.isdigit():
            int_count += 1
        else:
            other_id_count += 1

        if rec.get("decision") not in VALID_DECISIONS:
            bad_decision.append(sid)

    _log(
        f"Id shapes: c300_*={c300_count}, bare-int={int_count}, other={other_id_count}",
        log_path,
    )
    _log(f"Non-string ids (will be coerced): {non_string_ids}", log_path)

    if duplicates:
        preview = sorted(set(duplicates))[:20]
        _log(
            f"ERROR: duplicate ids found ({len(set(duplicates))} unique): {preview}"
            + (" ..." if len(set(duplicates)) > 20 else ""),
            log_path,
        )
        return 1
    _log("Id uniqueness: OK", log_path)

    if bad_decision:
        preview = bad_decision[:20]
        _log(
            f"WARNING: {len(bad_decision)} record(s) with missing/invalid `decision`: "
            f"{preview}" + (" ..." if len(bad_decision) > 20 else ""),
            log_path,
        )
    else:
        _log("Decision values: OK (all 'new' or 'practice')", log_path)

    # ---- Second pass: transform -----------------------------------------
    already_had_urgency = 0
    urgency_added = 0
    urgency_filled = 0

    for rec in records:
        rec["id"] = str(rec["id"])

        existing = rec.get("urgency_data")
        if isinstance(existing, dict):
            already_had_urgency += 1
            changed = False
            for k, v in EMPTY_URGENCY.items():
                if k not in existing:
                    existing[k] = list(v) if isinstance(v, list) else v
                    changed = True
            if changed:
                urgency_filled += 1
        else:
            rec["urgency_data"] = {
                k: (list(v) if isinstance(v, list) else v)
                for k, v in EMPTY_URGENCY.items()
            }
            urgency_added += 1

    _log(
        f"urgency_data: {urgency_added} added, {urgency_filled} filled in, "
        f"{already_had_urgency} already present",
        log_path,
    )

    # ---- Optional backup of destination if it already exists ------------
    if dst.exists():
        bak = dst.with_suffix(dst.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(dst, bak)
            _log(f"Backup written: {bak}", log_path)
        else:
            _log(f"Backup already exists, not overwriting: {bak}", log_path)

    _atomic_write_json(dst, records)
    _log(f"Wrote migrated file: {dst} ({len(records)} records)", log_path)
    _log("Migration complete.", log_path)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default=DEFAULT_SRC,
                        help=f"Source JSON (default: {DEFAULT_SRC})")
    parser.add_argument("--dst", default=DEFAULT_DST,
                        help=f"Destination JSON (default: {DEFAULT_DST})")
    parser.add_argument("--log", default=DEFAULT_LOG,
                        help=f"Log file (default: {DEFAULT_LOG})")
    args = parser.parse_args()

    return migrate(Path(args.src), Path(args.dst), Path(args.log))


if __name__ == "__main__":
    sys.exit(main())
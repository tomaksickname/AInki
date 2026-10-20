#!/usr/bin/env python3
"""
Compare practice word pool sizes: 5, 7, 10.

For each pool size, generate 10 sentences using the same 10 target words
and a fresh batch of practice words. Measure:
    - Words offered per card
    - Words actually used per card
    - Average usage
    - Sample sentences for quality review
"""

import json
import logging
import sys
from pathlib import Path

# Add src/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from file_manager import FileManager
from srs_engine import SRSEngine
from urgency_engine import UrgencyEngine
from sentence_generator import SentenceGenerator


logging.basicConfig(
    level=logging.WARNING,  # quiet — we only want results
    format="%(message)s",
)


def run_test(pool_size: int, target_words: list, practice_source: list, generator):
    """Run one test with a given pool size."""
    print(f"\n{'=' * 70}")
    print(f"  POOL SIZE = {pool_size}")
    print(f"{'=' * 70}")

    results = []
    total_used = 0

    for i, target in enumerate(target_words):
        # Take the next `pool_size` practice words from the source
        start = i * pool_size
        offered = practice_source[start:start + pool_size]

        if not offered:
            continue

        sentence = generator.generate_sentence(
            target_word=target,
            translation="",  # not needed for this test
            practice_words=offered,
            cefr_level="C1",
        )

        if not sentence:
            print(f"  ❌ {target}: generation failed")
            continue

        used = sentence.get("practice_words_used", [])
        total_used += len(used)

        results.append({
            "target": target,
            "offered": offered,
            "used": used,
            "russian": sentence["russian"],
            "english": sentence["english"],
        })

        print(f"\n  [{i + 1}] {target}")
        print(f"      Offered ({len(offered)}): {', '.join(offered)}")
        print(f"      Used ({len(used)}):    {', '.join(used) if used else '(none)'}")
        print(f"      RU: {sentence['russian']}")
        print(f"      EN: {sentence['english']}")

    avg = total_used / len(results) if results else 0
    print(f"\n  📊 AVERAGE USED PER SENTENCE: {avg:.2f}")
    print(f"  📊 TOTAL USED: {total_used} / {len(results) * pool_size} offered")

    return {
        "pool_size": pool_size,
        "avg_used": avg,
        "total_used": total_used,
        "results": results,
    }


def main():
    print("=" * 70)
    print("  AInki — Practice Word Pool Size Comparison")
    print("=" * 70)

    fm = FileManager()
    config = fm.get_config()

    # Force temperature to 0 for reproducibility? No — keep 0.7 to match prod.
    # But we use the same target words for all three tests, so it's comparable.

    generator = SentenceGenerator(config)
    srs = SRSEngine(config)
    urgency = UrgencyEngine(config)

    working = fm.load_working_data()
    words = working["decisions"]

    # ---------- Get the same 10 target words as the last daily run ----------
    # These are the first 10 new words by rank
    new_cards = srs.get_new_cards(words, count=10)
    target_words = [w["word"] for w in new_cards]

    print(f"\n🎯 Target words (same for all tests):")
    for i, t in enumerate(target_words, 1):
        print(f"   {i:>2}. {t}")

    # ---------- Load a large pool of practice words ----------
    # We'll take 200 practice words to distribute across the 3 tests
    practice_words = []
    for w in words:
        if w.get("decision") == "practice":
            practice_words.append(w["word"])

    # Dedupe
    seen = set()
    unique_practice = []
    for w in practice_words:
        if w not in seen:
            seen.add(w)
            unique_practice.append(w)

    print(f"\n📚 Practice pool: {len(unique_practice)} unique words")

    # ---------- Run three tests with the SAME practice words ----------
    # To compare fairly, we'll give each pool size access to the same
    # first N practice words, in the same order.

    # Use the first 200 practice words for all tests (same source)
    source_practice = unique_practice[:200]

    results = []
    for pool_size in [5, 7, 10]:
        r = run_test(pool_size, target_words, source_practice, generator)
        results.append(r)

    # ---------- Summary ----------
    print(f"\n\n{'=' * 70}")
    print("  SUMMARY")
    print(f"{'=' * 70}")
    print(f"\n  {'Pool Size':<12} {'Total Offered':<16} {'Total Used':<14} {'Avg Used/Sentence':<18}")
    print(f"  {'-' * 60}")
    for r in results:
        offered = len(r["results"]) * r["pool_size"]
        print(f"  {r['pool_size']:<12} {offered:<16} {r['total_used']:<14} {r['avg_used']:<18.2f}")

    print()
    print("  Look for: does avg_used plateau around 2-3? Does quality stay high?")
    print()


if __name__ == "__main__":
    main()

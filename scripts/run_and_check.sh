#!/bin/bash
cd "$(dirname "$0")/.."

echo "════════════════════════════════════════════════════════════════════"
echo "  AInki — Run & Check"
echo "════════════════════════════════════════════════════════════════════"
echo ""

POOL_SIZE=$(python3 -c "import json; print(json.load(open('config/config.json'))['sentence_settings']['practice_words_per_sentence'])")
echo "📋 Current pool size: $POOL_SIZE practice words per sentence"
echo ""

echo "▶️  Running daily generator..."
echo ""
python3 src/daily_generator.py
echo ""

echo "════════════════════════════════════════════════════════════════════"
echo "  Usage Analysis"
echo "════════════════════════════════════════════════════════════════════"
echo ""

python3 << 'PYEND'
import json
with open('data/vocabulary_data.json') as f:
    d = json.load(f)

rows = []
for w in d['decisions']:
    if w.get('sentences'):
        s = w['sentences'][-1]
        used = s.get('practice_words_used', [])
        rows.append((w['word'], len(used), used))

if not rows:
    print("No sentences found.")
    exit()

print(f"{'Word':<22} {'Used':>4}   Practice words used")
print("─" * 100)
for word, n, used in rows:
    used_str = ", ".join(used) if used else "(none)"
    print(f"{word:<22} {n:>4}   {used_str}")

total = sum(n for _, n, _ in rows)
avg = total / len(rows)

print("─" * 100)
print(f"{'TOTAL':<22} {total:>4}")
print(f"{'AVERAGE':<22} {avg:>4.2f}")
print()

dist = {}
for _, n, _ in rows:
    dist[n] = dist.get(n, 0) + 1

print("Distribution:")
for n in sorted(dist.keys()):
    bar = "█" * dist[n]
    print(f"  {n} used: {bar} ({dist[n]})")
print()

if avg >= 2.5:
    print(f"✅ Target 2-3: HIT (avg {avg:.2f})")
elif avg >= 2.0:
    print(f"🟡 Target 2-3: CLOSE (avg {avg:.2f})")
else:
    print(f"❌ Target 2-3: MISS (avg {avg:.2f})")
PYEND

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "  Done"
echo "════════════════════════════════════════════════════════════════════"

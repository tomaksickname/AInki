import json
from datetime import date

with open('data/vocabulary_data.json') as f:
    data = json.load(f)

cards = data['decisions']
today = date.today().isoformat()

new_unintro = [c for c in cards if c.get('decision') == 'new' and not c.get('srs_data', {}).get('introduced_date')]
introduced = [c for c in cards if c.get('srs_data', {}).get('introduced_date')]
due_reviews = [c for c in introduced if (c.get('srs_data', {}).get('due_date') or '9999') <= today]

# State breakdown among introduced cards
from collections import Counter
states = Counter(c.get('srs_data', {}).get('state', 'none') for c in introduced)

print(f"Total cards:      {len(cards)}")
print(f"New (unintro):    {len(new_unintro)}")
print(f"Introduced:       {len(introduced)}")
print(f"Due reviews:      {len(due_reviews)}")
print()
print("States among introduced:", dict(states))
print()
print("Sample of introduced cards:")
for c in introduced[:15]:
    srs = c.get('srs_data', {})
    print(f"  {c.get('word', '?'):20} | state={srs.get('state'):10} | due={srs.get('due_date')} | intro={srs.get('introduced_date')}")

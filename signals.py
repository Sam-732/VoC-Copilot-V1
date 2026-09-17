import sqlite3, re, collections
from themes import THEMES

con = sqlite3.connect("reviews.db")
rows = con.execute("""
    SELECT c.cluster, r.content FROM clusters c
    JOIN reviews_raw r ON r.review_id = c.review_id
    WHERE c.cluster != -1
""").fetchall()
con.close()

SIGNALS = {
  "distance/km":  r"\b\d+\s?k ?m\b|distance|kilomet|google maps|far away",
  "refund":       r"refund|paisa wapas|money back",
  "chatbot/AI":   r"\bbot\b|chatbot|\bai\b|human agent|executive",
  "cancellation": r"cancel",
  "late/delay":   r"late|delay|hour|hrs|mint|minut",
  "fees/charges": r"\bfee|charge|surge|\btax|gst|platform fee",
}

kept = [(c, t or "") for c, t in rows if c in THEMES]
print(f"{len(kept)} reviews in themes\n")

for name, pat in SIGNALS.items():
    rx = re.compile(pat, re.I)
    hits = [(c, t) for c, t in kept if rx.search(t)]
    spread = collections.Counter(THEMES[c] for c, _ in hits)
    print(f"{name:14} {len(hits):4} reviews ({len(hits)/len(kept)*100:.0f}%)")
    for th, n in spread.most_common(3):
        print(f"               {n:4}  in {th[:55]}")
    print()
import sqlite3, collections

con = sqlite3.connect("reviews.db")
rows = con.execute("""
    SELECT c.cluster, r.score, r.text
    FROM clusters c JOIN reviews_clean r ON r.review_id = c.review_id
    WHERE c.cluster != -1
""").fetchall()
con.close()

by_c = collections.defaultdict(list)
for cid, score, text in rows:
    by_c[cid].append((score, text))

for cid, items in sorted(by_c.items(), key=lambda x: -len(x[1])):
    avg = sum(s for s, _ in items) / len(items)
    print(f"=== cluster {cid} | {len(items)} reviews | mean {avg:.1f} stars ===")
    print("THEME: ________________________")
    for s, t in items[:8]:
        print(f"  {s}* {t[:150]}")
    print()
import sqlite3, collections
con = sqlite3.connect("reviews.db")
rows = con.execute("""
    SELECT c.cluster, r.text FROM clusters c
    JOIN reviews_clean r ON r.review_id = c.review_id
""").fetchall()

cnt = collections.Counter(c for c, _ in rows)
total = len(rows)
print(f"total: {total}")
print(f"noise: {cnt[-1]} ({cnt[-1]/total*100:.0f}%)")
print(f"clusters: {len([k for k in cnt if k != -1])}\n")

for cid, n in sorted([(k,v) for k,v in cnt.items() if k != -1], key=lambda x: -x[1]):
    print(f"--- cluster {cid}  ({n} reviews) ---")
    for _, t in [r for r in rows if r[0] == cid][:3]:
        print("   ", t[:100])
    print()
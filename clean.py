import sqlite3, re

con = sqlite3.connect("reviews.db")
con.execute("DROP TABLE IF EXISTS reviews_clean")
con.execute("""
CREATE TABLE reviews_clean (
    review_id TEXT PRIMARY KEY, text TEXT, score INTEGER,
    at TEXT, app_version TEXT, dupe_count INTEGER
)""")

rows = con.execute(
    "SELECT review_id, content, score, at, app_version FROM reviews_raw "
    "WHERE content IS NOT NULL AND TRIM(content) != ''").fetchall()

def clean(t):
    t = re.sub(r'(.)\1{2,}', r'\1\1', t)     # sirrrrr -> sirr, goooood -> good
    t = re.sub(r'([!?.,])\1+', r'\1', t)     # !!!!! -> !
    return re.sub(r'\s+', ' ', t).strip()

seen, order = {}, []
for rid, content, score, at, ver in rows:
    t = clean(content)
    if len(t.split()) < 5:
        continue
    key = t.lower()
    if key in seen:
        seen[key][1] += 1
    else:
        seen[key] = [(rid, t, score, at, ver), 1]
        order.append(key)

out = [(*seen[k][0], seen[k][1]) for k in order]
con.executemany("INSERT INTO reviews_clean VALUES (?,?,?,?,?,?)", out)
con.commit()

print("raw with text:      ", len(rows))
print("kept after cleaning:", len(out))
print("dupes collapsed:    ", sum(v[1]-1 for v in seen.values()))
print("\nmost repeated texts:")
for k in sorted(seen, key=lambda k: -seen[k][1])[:8]:
    print(f"  x{seen[k][1]:3}  {seen[k][0][1][:70]}")
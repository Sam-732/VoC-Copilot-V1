import sqlite3, csv, random

con = sqlite3.connect("reviews.db")
rows = con.execute(
    "SELECT review_id, at, score, content FROM reviews_raw "
    "WHERE content IS NOT NULL AND length(content) > 0 "
    "AND score <= 4"
).fetchall()
con.close()

random.seed(42)
sample = random.sample(rows, 200)

with open("sample.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["review_id", "date", "stars", "text", "my_label"])
    w.writerows(sample)

print(f"wrote {len(sample)} of {len(rows)}")
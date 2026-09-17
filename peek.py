import sqlite3
con = sqlite3.connect("reviews.db")

q = lambda s: con.execute(s).fetchone()[0]

print("total rows:  ", q("SELECT COUNT(*) FROM reviews_raw"))
print("has text:    ", q("SELECT COUNT(*) FROM reviews_raw WHERE content IS NOT NULL AND TRIM(content) != ''"))
print("<=3 words:   ", q("SELECT COUNT(*) FROM reviews_raw WHERE content IS NOT NULL "
                         "AND LENGTH(TRIM(content)) - LENGTH(REPLACE(TRIM(content),' ','')) < 3"))
print("no version:  ", q("SELECT COUNT(*) FROM reviews_raw WHERE app_version IS NULL"))

print("\nstars:")
for star, n in con.execute("SELECT score, COUNT(*) FROM reviews_raw GROUP BY score ORDER BY score"):
    print(f"  {star}★  {n}")

con.close()
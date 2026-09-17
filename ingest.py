import sqlite3, time
from datetime import datetime, timedelta
from google_play_scraper import reviews, Sort

APP_ID = "in.swiggy.android"
DAYS   = 30
DB     = "reviews.db"

cutoff = datetime.now() - timedelta(days=DAYS)
fetched_at = datetime.now().isoformat()

con = sqlite3.connect(DB)
con.execute("""
CREATE TABLE IF NOT EXISTS reviews_raw (
    review_id   TEXT PRIMARY KEY,
    content     TEXT,
    score       INTEGER,
    at          TEXT,
    app_version TEXT,
    thumbs_up   INTEGER,
    fetched_at  TEXT
)
""")
con.commit()

token = None
total = 0

while True:
    batch, token = reviews(
        APP_ID, lang="en", country="in", sort=Sort.NEWEST,
        count=200, continuation_token=token,
    )

    if not batch:
        print("empty batch, stopping")
        break

    rows = [(r["reviewId"], r["content"], r["score"], r["at"].isoformat(),
             r.get("reviewCreatedVersion"), r.get("thumbsUpCount"), fetched_at)
            for r in batch]

    con.executemany(
        "INSERT INTO reviews_raw VALUES (?,?,?,?,?,?,?) ON CONFLICT(review_id) DO NOTHING",
        rows,
    )
    con.commit()
    total += len(batch)

    oldest = batch[-1]["at"]
    print(f"saved {len(batch)} | running total {total} | oldest {oldest}")

    if oldest < cutoff:
        print("reached 30-day cutoff")
        break
    if token is None:
        print("Play stopped giving continuation tokens")
        break

    time.sleep(1)

n = con.execute("SELECT COUNT(*) FROM reviews_raw").fetchone()[0]
print(f"done — {n} reviews in {DB}")
con.close()
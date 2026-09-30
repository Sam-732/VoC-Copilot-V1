"""
Daily ingestion (v2, phase 1).

Fetches only reviews newer than the newest one already in reviews_raw, dedupes on review ID,
appends them to reviews_raw, and runs v1's cleaning on just the new rows into reviews_clean.
Every run is recorded in ingest_runs.

A run either commits everything or nothing. If it fails, reviews_raw is untouched, so its
newest timestamp is still the last successful one and tomorrow's run picks up from there.

    python daily_ingest.py              # normal run
    python daily_ingest.py --dry-run    # fetch and report, write nothing (not even a run record)

Exit codes: 0 ok, 1 failed (nothing written), 2 ok but anomalous. Task Scheduler shows non-zero.
"""
import argparse, logging, os, sqlite3, sys, time
from datetime import datetime
from google_play_scraper import reviews, Sort

import config as C
from cleaning import clean, is_substantive, dedupe_key

log = logging.getLogger("ingest")

RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT,
    finished_at      TEXT,
    status           TEXT,     -- running | success | failed
    watermark_before TEXT,     -- newest review 'at' before the run
    watermark_after  TEXT,
    pages            INTEGER,
    fetched          INTEGER,  -- reviews returned at/after the watermark
    dupes_in_fetch   INTEGER,  -- same review ID twice within this fetch
    already_in_db    INTEGER,  -- review ID already stored
    inserted         INTEGER,  -- new rows in reviews_raw
    clean_inserted   INTEGER,  -- new rows in reviews_clean
    clean_too_short  INTEGER,
    clean_dupe_text  INTEGER,  -- text already in reviews_clean; dupe_count bumped instead
    days_covered     REAL,
    per_day          REAL,
    anomalous        INTEGER,
    anomaly_reason   TEXT,
    error            TEXT
)"""


class IncompleteFetch(Exception):
    pass


def setup_logging():
    if log.handlers:
        return
    os.makedirs(C.LOG_DIR, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(os.path.join(C.LOG_DIR, C.INGEST_LOG_FILE), encoding="utf-8")
    sh = logging.StreamHandler(sys.stdout)
    for h in (fh, sh):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def get_watermark(con):
    at = con.execute("SELECT MAX(at) FROM reviews_raw").fetchone()[0]
    if at is None:
        raise RuntimeError("reviews_raw is empty - run v1 ingest.py first to build the base corpus")
    return datetime.fromisoformat(at)


def fetch_page(token):
    # google-play-scraper swallows network errors and returns an empty page, so an empty page
    # before we reach the watermark is treated as a failure and retried.
    for attempt in range(1, C.FETCH_RETRIES + 1):
        try:
            batch, token = reviews(C.APP_ID, lang=C.SCRAPE_LANG, country=C.SCRAPE_COUNTRY,
                                   sort=Sort.NEWEST, count=C.PAGE_SIZE, continuation_token=token)
            if batch:
                return batch, token
            log.warning(f"empty page (attempt {attempt}/{C.FETCH_RETRIES})")
        except Exception as e:
            log.warning(f"scraper error (attempt {attempt}/{C.FETCH_RETRIES}): {e!r}")
        if attempt < C.FETCH_RETRIES:
            time.sleep(C.RETRY_BACKOFF_SECONDS * attempt)
    return [], None


def fetch_since(watermark):
    """All reviews with at >= watermark, newest first. >= (not >) so a review sharing the
    watermark's second is not lost; the ID dedupe drops the one we already have."""
    token, pages, out = None, 0, []
    while True:
        if pages >= C.MAX_PAGES:
            raise IncompleteFetch(f"hit MAX_PAGES={C.MAX_PAGES} before reaching {watermark}; "
                                  "raise MAX_PAGES in config.py for a catch-up run")
        batch, token = fetch_page(token)
        if not batch:
            if pages == 0:
                return out, pages          # nothing at all: reported as anomalous, not failed
            raise IncompleteFetch(f"feed ended after {pages} pages without reaching {watermark}; "
                                  "not inserting, to avoid leaving a gap")
        pages += 1
        new = [r for r in batch if r["at"] >= watermark]
        out.extend(new)
        log.info(f"page {pages}: {len(batch)} returned, {len(new)} new | oldest {batch[-1]['at']}")
        if batch[-1]["at"] < watermark:
            return out, pages
        if token is None or getattr(token, "token", None) is None:
            raise IncompleteFetch("Play stopped returning continuation tokens before the watermark")
        time.sleep(C.PAGE_SLEEP_SECONDS)


def insert_raw(con, fetched, fetched_at):
    by_id = {}
    for r in fetched:
        by_id.setdefault(r["reviewId"], r)
    dupes_in_fetch = len(fetched) - len(by_id)

    ids = list(by_id)
    existing = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = f"SELECT review_id FROM reviews_raw WHERE review_id IN ({','.join('?' * len(chunk))})"
        existing.update(x[0] for x in con.execute(q, chunk))

    new = [by_id[i] for i in ids if i not in existing]
    # same row shape as v1 ingest.py
    con.executemany(
        "INSERT INTO reviews_raw VALUES (?,?,?,?,?,?,?)",
        [(r["reviewId"], r["content"], r["score"], r["at"].isoformat(),
          r.get("reviewCreatedVersion"), r.get("thumbsUpCount"), fetched_at) for r in new])
    return new, dupes_in_fetch, len(existing)


def clean_new(con, new):
    """v1 clean.py rules, applied to just the new rows."""
    known = {dedupe_key(t): rid for rid, t in con.execute("SELECT review_id, text FROM reviews_clean")}
    inserted = short = dupe = 0
    for r in new:
        if not r["content"] or not r["content"].strip():
            continue
        t = clean(r["content"])
        if not is_substantive(t):
            short += 1
            continue
        k = dedupe_key(t)
        if k in known:
            con.execute("UPDATE reviews_clean SET dupe_count = dupe_count + 1 WHERE review_id = ?",
                        (known[k],))
            dupe += 1
            continue
        con.execute("INSERT INTO reviews_clean VALUES (?,?,?,?,?,?)",
                    (r["reviewId"], t, r["score"], r["at"].isoformat(),
                     r.get("reviewCreatedVersion"), 1))
        known[k] = r["reviewId"]
        inserted += 1
    return inserted, short, dupe


def assess(fetched_n, watermark, now):
    days = max((now - watermark).total_seconds() / 86400, C.MIN_DAYS_FOR_RATE)
    per_day = fetched_n / days
    reason = None
    if fetched_n == 0:
        reason = "zero reviews returned (scraper hides network/rate-limit errors as empty results)"
    elif per_day < C.ANOMALY_MIN_PER_DAY:
        reason = f"{per_day:.0f}/day is below ANOMALY_MIN_PER_DAY={C.ANOMALY_MIN_PER_DAY}"
    elif per_day > C.ANOMALY_MAX_PER_DAY:
        reason = f"{per_day:.0f}/day is above ANOMALY_MAX_PER_DAY={C.ANOMALY_MAX_PER_DAY}"
    return days, per_day, reason


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    setup_logging()

    started = datetime.now()
    log.info(f"=== ingest run start{' (dry run)' if args.dry_run else ''} ===")
    con, run_id = None, None
    try:
        con = sqlite3.connect(C.DB_PATH)
        con.execute(RUNS_SCHEMA)
        con.commit()
        watermark = get_watermark(con)
        log.info(f"newest stored review: {watermark}")

        if not args.dry_run:
            cur = con.execute("INSERT INTO ingest_runs (started_at, status, watermark_before) "
                              "VALUES (?, 'running', ?)", (started.isoformat(), watermark.isoformat()))
            run_id = cur.lastrowid
            con.commit()

        fetched, pages = fetch_since(watermark)
        days, per_day, reason = assess(len(fetched), watermark, datetime.now())
        log.info(f"fetched {len(fetched)} reviews over {pages} pages "
                 f"({days:.1f} days covered, {per_day:.0f}/day)")
        if reason:
            log.warning(f"ANOMALY: {reason}")

        if args.dry_run:
            log.info("dry run - nothing written")
            return 2 if reason else 0

        # one transaction: raw inserts, clean inserts, run record
        new, dupes_in_fetch, already = insert_raw(con, fetched, started.isoformat())
        c_ins, c_short, c_dupe = clean_new(con, new)
        wm_after = con.execute("SELECT MAX(at) FROM reviews_raw").fetchone()[0]
        con.execute("""UPDATE ingest_runs SET finished_at=?, status='success', watermark_after=?,
                       pages=?, fetched=?, dupes_in_fetch=?, already_in_db=?, inserted=?,
                       clean_inserted=?, clean_too_short=?, clean_dupe_text=?,
                       days_covered=?, per_day=?, anomalous=?, anomaly_reason=? WHERE run_id=?""",
                    (datetime.now().isoformat(), wm_after, pages, len(fetched), dupes_in_fetch,
                     already, len(new), c_ins, c_short, c_dupe, round(days, 2), round(per_day, 1),
                     int(bool(reason)), reason, run_id))
        con.commit()

        log.info(f"dedupe: {dupes_in_fetch} repeated within fetch, {already} already stored")
        log.info(f"inserted {len(new)} into reviews_raw")
        log.info(f"cleaning: {c_ins} into reviews_clean, {c_short} under {C.MIN_WORDS} words, "
                 f"{c_dupe} duplicate text")
        log.info(f"newest stored review now: {wm_after}")
        log.info(f"=== run {run_id} success{' (ANOMALOUS)' if reason else ''} ===")
        return 2 if reason else 0

    except Exception as e:
        log.error(f"run failed: {e!r}")
        if con is not None:
            con.rollback()
            if run_id is not None:
                try:
                    con.execute("UPDATE ingest_runs SET finished_at=?, status='failed', error=? "
                                "WHERE run_id=?", (datetime.now().isoformat(), repr(e), run_id))
                    con.commit()
                except Exception as e2:
                    log.error(f"could not record failure: {e2!r}")
        log.info(f"=== run {run_id} failed - database unchanged ===")
        return 1
    finally:
        if con is not None:
            con.close()


if __name__ == "__main__":
    sys.exit(main())

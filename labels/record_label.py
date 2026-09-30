"""
Append hand verdicts on borderline assignments to labels/threshold_labels.csv.

One at a time:
    python labels/record_label.py LOG_ID right|wrong "reasoning" ["failure type"]
A filled-in batch from `assignlog.py labelset` (rows with an empty verdict are skipped):
    python labels/record_label.py --from-csv labels/batch_XXXX.csv

cluster / second_cluster are internal ids (as in reviews.db); *_display_id are the ids from
themes_v2.json that the dashboard shows. The CSV keeps the numbers as they were when the verdict was given (metric, threshold,
distances), so the record stays meaningful after the threshold or metric changes.
A log id that's already recorded is skipped, not duplicated.
"""
import csv, json, os, sqlite3, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.chdir(os.path.dirname(HERE))
import config as C
import taxonomy

OUT = os.path.join(HERE, "threshold_labels.csv")
FIELDS = ["labelled_at", "log_id", "pool", "metric", "threshold_at_label", "stars",
          "cluster", "cluster_display_id", "cluster_label", "distance",
          "second_cluster", "second_display_id", "second_label",
          "second_distance", "gap", "verdict", "failure_type", "reasoning", "review_id", "text"]


def recorded():
    if not os.path.exists(OUT):
        return set()
    with open(OUT, encoding="utf-8-sig") as f:
        return {int(r["log_id"]) for r in csv.DictReader(f)}


def session_pool(log_id):
    path = os.path.join(HERE, "_session.json")
    if not os.path.exists(path):
        return ""
    return dict(map(tuple, json.load(open(path))["picks"])).get(log_id, "")


def record(con, log_id, verdict, reasoning, failure_type="", pool=None):
    verdict = verdict.strip().lower()
    if verdict not in ("right", "wrong"):
        sys.exit(f"log {log_id}: verdict must be right or wrong, got {verdict!r}")
    if log_id in recorded():
        print(f"log {log_id} already recorded - skipped")
        return False
    r = con.execute("""SELECT l.metric, l.threshold, c.score, l.cluster, l.cluster_label, l.distance,
                       l.second_cluster, l.second_label, l.second_distance, l.gap, l.review_id, c.text
                       FROM assignment_log l JOIN reviews_clean c USING (review_id)
                       WHERE l.log_id = ?""", (log_id,)).fetchone()
    if not r:
        sys.exit(f"no log row {log_id}")
    _, clusters = taxonomy.load([x for x in (r[3], r[6]) if x is not None])
    disp = lambda c: clusters[c]["id"] if c is not None else ""
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(FIELDS)
        w.writerow([datetime.now().isoformat(timespec="seconds"), log_id,
                    pool if pool is not None else session_pool(log_id), *r[:4], disp(r[3]), *r[4:6],
                    r[6], disp(r[6]), *r[7:10],
                    verdict, failure_type, reasoning, r[10], r[11]])
    print(f"recorded log {log_id}: {verdict}")
    return True


def main():
    con = sqlite3.connect(C.DB_PATH)
    if sys.argv[1] == "--from-csv":
        with open(sys.argv[2], encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        done = [r for r in rows if r.get("verdict", "").strip()]
        n = sum(record(con, int(r["log_id"]), r["verdict"], r.get("reason", ""),
                       r.get("failure_type", ""), r.get("pool", "")) for r in done)
        print(f"{n} recorded, {len(rows) - len(done)} rows without a verdict left out")
        return
    record(con, int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")


if __name__ == "__main__":
    main()

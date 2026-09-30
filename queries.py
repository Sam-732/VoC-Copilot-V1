"""
Read-only lookups for the web app's pages (v2, phase 4, step 2). Every function takes an open
connection and only runs SELECTs; app.py passes a connection that refuses writes anyway.

Cluster numbers returned here are display ids (themes_v2.json), never internal ids.
"""
import collections, json
from datetime import date, timedelta

import numpy as np

import config as C
import space as S
import taxonomy


def _taxonomy(con):
    ids = [c for (c,) in con.execute("SELECT cluster FROM centroids")]
    themes, clusters = taxonomy.load(ids)
    return themes, clusters


def _since_reset(con):
    return con.execute("SELECT COALESCE(MAX(run_id), 0) FROM assign_runs WHERE status='reset'").fetchone()[0]


def trends(con):
    """Complaint themes per day (by review date), rank per run, bucket size per run."""
    themes, clusters = _taxonomy(con)
    rows = con.execute("""SELECT a.status, a.cluster, substr(r.at, 1, 10) FROM assignments a
                          JOIN reviews_raw r USING (review_id)
                          WHERE a.status IN ('clustered', 'unassigned')""").fetchall()
    first = date.fromisoformat(min(d for *_, d in rows))
    last = date.fromisoformat(max(d for *_, d in rows))
    days = [(first + timedelta(i)).isoformat() for i in range((last - first).days + 1)]
    idx = {d: i for i, d in enumerate(days)}
    per = collections.defaultdict(lambda: [0] * len(days))
    for status, c, d in rows:
        key = clusters[c]["theme"] if status == "clustered" else "_bucket"
        per[key][idx[d]] += 1
    v2start = con.execute("""SELECT MIN(substr(c.at,1,10)) FROM assignments a JOIN reviews_clean c
                             USING (review_id) WHERE a.source != 'initial'""").fetchone()[0]

    reset = _since_reset(con)
    runs = [r for (r,) in con.execute("SELECT DISTINCT run_id FROM theme_rank_snapshots WHERE run_id >= ? "
                                      "ORDER BY run_id", (reset,))]
    def run_label(r):
        if r == reset:
            return "v1 only"
        d = con.execute("""SELECT MAX(substr(c.at,1,10)) FROM assignment_log l JOIN reviews_clean c
                           USING (review_id) WHERE l.run_id = ?""", (r,)).fetchone()[0]
        return f"to {d[5:]}" if d else f"run {r}"
    snaps = collections.defaultdict(dict)
    for r, k, rank, total in con.execute("SELECT run_id, theme, rank, total FROM theme_rank_snapshots "
                                         "WHERE run_id >= ?", (reset,)):
        snaps[k][r] = (rank, total)
    bucket_by_run = dict(con.execute("SELECT run_id, total FROM rank_snapshots WHERE grp='bucket' "
                                     "AND run_id >= ?", (reset,)))

    comp = [t for t in themes.values() if t["kind"] == "complaint"]
    latest = runs[-1]
    comp.sort(key=lambda t: snaps[t["key"]][latest][0])
    return {
        "days": days, "v2start": v2start,
        "themes": [{"key": t["key"], "name": t["name"], "daily": per[t["key"]],
                    "total": sum(per[t["key"]]), "ranks": [snaps[t["key"]].get(r, (None, None))[0] for r in runs]}
                   for t in comp],
        "bucket_daily": per["_bucket"],
        "runs": [{"id": r, "label": run_label(r), "bucket": bucket_by_run.get(r)} for r in runs],
    }


def bucket(con, sort="distance"):
    """Unassigned reviews with their nearest cluster, plus each cluster found in the bucket."""
    themes, clusters = _taxonomy(con)
    tname = {k: t["name"] for k, t in themes.items()}
    order = {"distance": "a.nearest_distance DESC", "date": "r.at DESC", "helpful": "r.thumbs_up DESC"}[sort]
    unassigned = [{"nearest": clusters[c]["id"], "nearest_theme": tname[clusters[c]["theme"]],
                   "distance": d, "stars": s, "date": at[:10], "helpful": u or 0, "text": t}
                  for c, d, s, at, u, t in con.execute(f"""
                      SELECT a.nearest_cluster, a.nearest_distance, r.score, r.at, r.thumbs_up, r.content
                      FROM assignments a JOIN reviews_raw r USING (review_id)
                      WHERE a.status = 'unassigned' ORDER BY {order}""")]

    ids, cents, ns = S.load_centroids(con)
    found = []
    for i in themes[taxonomy.UNMAPPED_THEME]["clusters"]:
        c = next(k for k, v in clusters.items() if v["id"] == i)
        rows = con.execute("""SELECT r.score, substr(r.at,1,10), COALESCE(r.thumbs_up,0), a.distance, r.content
                              FROM assignments a JOIN reviews_raw r USING (review_id)
                              WHERE a.cluster = ? AND a.status = 'clustered'""", (c,)).fetchall()
        D = S.distances(cents[[ids.index(c)]], cents)[0]
        near = sorted((D[k], x) for k, x in enumerate(ids) if x != c)[:C.CARD_NEAREST_N]
        stars = collections.Counter(r[0] for r in rows)
        created_run = con.execute("SELECT created_run FROM centroids WHERE cluster = ?", (c,)).fetchone()[0]
        found.append({
            "id": i, "size": len(rows), "size_at_creation": ns[c], "created_run": created_run,
            "mean": float(np.mean([r[0] for r in rows])),
            "stars": [stars.get(k, 0) for k in range(1, 6)],
            "first": min(r[1] for r in rows), "last": max(r[1] for r in rows),
            "radius": float(np.median([r[3] for r in rows])),
            "nearest": [{"id": clusters[x]["id"], "theme": tname[clusters[x]["theme"]], "distance": float(d)}
                        for d, x in near],
            "typical": [{"stars": r[0], "date": r[1], "helpful": r[2], "text": r[4]}
                        for r in sorted(rows, key=lambda r: r[3])[:C.BUCKET_TYPICAL_N]],
        })
    found.sort(key=lambda f: -f["size"])
    return {"unassigned": unassigned, "found": found, "sort": sort}


def search(con, q):
    """Reviews whose raw text contains q (case-insensitive), with where each one sits now."""
    q = (q or "").strip()
    if len(q) < C.SEARCH_MIN_CHARS:
        return {"q": q, "results": [], "total": 0, "too_short": bool(q)}
    themes, clusters = _taxonomy(con)
    tname = {k: t["name"] for k, t in themes.items()}
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    where = "FROM reviews_raw r LEFT JOIN assignments a USING (review_id) WHERE r.content LIKE ? ESCAPE '\\'"
    total = con.execute(f"SELECT COUNT(*) {where}", (like,)).fetchone()[0]
    results = []
    for s, at, u, t, status, c in con.execute(
            f"SELECT r.score, r.at, r.thumbs_up, r.content, a.status, a.cluster {where} "
            f"ORDER BY r.thumbs_up DESC, r.at DESC LIMIT ?", (like, C.SEARCH_MAX_RESULTS)):
        if status == "clustered":
            where_now = f"{tname[clusters[c]['theme']]} · sub-theme {clusters[c]['id']}"
        elif status == "unassigned":
            where_now = "Unassigned bucket"
        elif status == "noise":
            where_now = "v1 noise (never clustered)"
        else:
            where_now = "Not clustered (under 5 words or duplicate text)"
        results.append({"stars": s, "date": at[:10], "helpful": u or 0, "text": t, "where": where_now})
    return {"q": q, "results": results, "total": total, "too_short": False}


def runs(con):
    """Every ingest run and every assign run, newest first."""
    ingest = [dict(zip(("id", "started", "finished", "status", "since", "newest", "fetched", "inserted",
                        "clean_inserted", "per_day", "anomalous", "anomaly", "error"), r))
              for r in con.execute("""SELECT run_id, started_at, finished_at, status, watermark_before,
                                      watermark_after, fetched, inserted, clean_inserted, per_day,
                                      anomalous, anomaly_reason, error
                                      FROM ingest_runs ORDER BY run_id DESC""")]
    assign = [dict(zip(("id", "started", "status", "threshold", "pending", "assigned", "unassigned",
                        "bucket_after", "new_clusters", "error"), r))
              for r in con.execute("""SELECT run_id, started_at, status, threshold, pending, assigned,
                                      unassigned, bucket_after, new_clusters, error
                                      FROM assign_runs ORDER BY run_id DESC""")]
    return {"ingest": ingest, "assign": assign, "current_from": _since_reset(con)}

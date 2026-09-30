"""
Incremental assignment (v2, phase 2). Run after daily_ingest.py.

Every review in reviews_clean without an `assignments` row is embedded with v1's MiniLM,
projected into v1's UMAP space (models/umap_v1.joblib, made by bootstrap_v2.py), and compared
to every cluster centroid (distance metric: config.DISTANCE_METRIC):
    nearest distance <  ASSIGNMENT_THRESHOLD -> joins that cluster
    otherwise                               -> unassigned bucket
The whole batch is judged against the centroids as they stood at the start of the run, so the
result does not depend on processing order. With FREEZE_CENTROIDS = False, centroids of clusters
that gained members are then updated (running mean); with True they never move.

If the bucket then holds more than BUCKET_RECLUSTER_MIN reviews, HDBSCAN (v1 parameters) runs
on the bucket alone. Clusters it finds get new ids and centroids and join the main structure;
the rest stay in the bucket. The full corpus is never re-clustered.

Every decision is also appended to assignment_log (read it with assignlog.py). --reset never
touches the log or the wrong-assignment flags.

    python assign.py                          # assign everything pending
    python assign.py --through 2026-09-15     # only reviews dated up to and including that day
    python assign.py --reset                  # discard all non-v1 assignments, restore v1 centroids

Exit codes: 0 ok, 1 failed (nothing written).
"""
import argparse, sqlite3, sys
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
import numpy as np

import config as C
import space as S


def reset(con):
    with con:
        n = con.execute("DELETE FROM assignments WHERE source != 'initial'").rowcount
        k = con.execute("DELETE FROM centroids WHERE origin != 'initial'").rowcount
        members = defaultdict(list)
        for cid, red in con.execute("""SELECT a.cluster, v.red FROM assignments a
                                       JOIN review_vectors v USING (review_id)
                                       WHERE a.source = 'initial' AND a.status = 'clustered'"""):
            members[cid].append(S.from_blob(red))
        now = datetime.now().isoformat()
        for cid, vs in members.items():
            con.execute("UPDATE centroids SET vec=?, n_members=?, updated_at=? WHERE cluster=?",
                        (S.to_blob(np.mean(vs, axis=0)), len(vs), now, cid))
        # v1 reviews' own distances, recomputed so they're in the current metric
        cids, cents, _ = S.load_centroids(con)
        col = {c: k for k, c in enumerate(cids)}
        init = con.execute("""SELECT a.review_id, a.cluster, v.red FROM assignments a
                              JOIN review_vectors v USING (review_id)
                              WHERE a.source = 'initial'""").fetchall()
        X = np.stack([S.from_blob(r[2]) for r in init])
        n1, d1, n2, d2, D = S.nearest_two(X, cids, cents)
        con.executemany("""UPDATE assignments SET distance=?, nearest_cluster=?, nearest_distance=?,
                           second_cluster=?, second_distance=? WHERE review_id=?""",
                        [(float(D[k, col[r[1]]]) if r[1] is not None else None, int(n1[k]),
                          float(d1[k]), int(n2[k]), float(d2[k]), r[0]) for k, r in enumerate(init)])
        # marker: assignlog.py treats runs after the latest reset as "current"
        con.execute("INSERT INTO assign_runs (started_at, finished_at, status, threshold) "
                    "VALUES (?, ?, 'reset', ?)", (now, now, C.ASSIGNMENT_THRESHOLD))
    print(f"reset: removed {n} incremental assignments and {k} bucket clusters; "
          f"{len(members)} v1 centroids restored; v1 distances recomputed ({C.DISTANCE_METRIC})")


def load_or_make_vectors(con, pending):
    ids = [p[0] for p in pending]
    have = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = f"SELECT review_id, red FROM review_vectors WHERE review_id IN ({','.join('?' * len(chunk))})"
        have.update((rid, S.from_blob(b)) for rid, b in con.execute(q, chunk))
    todo = [p for p in pending if p[0] not in have]
    if todo:
        print(f"embedding and projecting {len(todo)} reviews...")
        emb = S.embed([p[1] for p in todo])
        red = S.load_reducer().transform(emb)
        con.executemany("INSERT INTO review_vectors VALUES (?,?,?)",
                        [(p[0], S.to_blob(e), S.to_blob(r)) for p, e, r in zip(todo, emb, red)])
        have.update((p[0], r) for p, r in zip(todo, red))
    return np.stack([have[i] for i in ids])


def update_centroids(con, gains, now):
    """gains: cluster -> list of new member vectors. Running mean."""
    for cid, vs in gains.items():
        vec, n = con.execute("SELECT vec, n_members FROM centroids WHERE cluster=?", (cid,)).fetchone()
        new = (S.from_blob(vec).astype(np.float64) * n + np.sum(vs, axis=0)) / (n + len(vs))
        con.execute("UPDATE centroids SET vec=?, n_members=?, updated_at=? WHERE cluster=?",
                    (S.to_blob(new), n + len(vs), now, cid))


def recluster_bucket(con, run_id, now):
    import hdbscan
    rows = con.execute("""SELECT a.review_id, v.red FROM assignments a
                          JOIN review_vectors v USING (review_id)
                          WHERE a.status = 'unassigned' ORDER BY a.review_id""").fetchall()
    if len(rows) <= C.BUCKET_RECLUSTER_MIN:
        return 0, 0
    print(f"bucket holds {len(rows)} > {C.BUCKET_RECLUSTER_MIN}: re-clustering the bucket alone")
    X = np.stack([S.from_blob(r[1]) for r in rows])
    lab = hdbscan.HDBSCAN(min_cluster_size=C.HDBSCAN_MIN_CLUSTER_SIZE,
                          min_samples=C.HDBSCAN_MIN_SAMPLES, metric=C.HDBSCAN_METRIC,
                          cluster_selection_method=C.HDBSCAN_SELECTION).fit_predict(X)
    found = sorted(set(lab) - {-1})
    if not found:
        print("   no cluster found in the bucket")
        return 0, 0

    # Never reuse an id. --reset deletes bucket clusters' centroids but the log keeps their ids,
    # so allocating from centroids alone let a new cluster take a discarded cluster's number.
    top = con.execute("""SELECT MAX(x) FROM (
                           SELECT MAX(cluster) AS x FROM centroids
                           UNION ALL SELECT MAX(cluster) FROM assignment_log
                           UNION ALL SELECT MAX(nearest_cluster) FROM assignment_log
                           UNION ALL SELECT MAX(second_cluster) FROM assignment_log)""").fetchone()[0]
    next_id = max(top + 1, C.EMERGENT_CLUSTER_ID_START)
    for l in found:
        m = lab == l
        con.execute("INSERT INTO centroids VALUES (?,?,?,?,?,?,?)",
                    (next_id, S.to_blob(X[m].mean(axis=0)), int(m.sum()), "bucket_recluster",
                     now, now, run_id))
        print(f"   new cluster {next_id}: {m.sum()} reviews")
        lab[m] = next_id           # relabel in place to the permanent id
        next_id += 1

    cids, cents, _ = S.load_centroids(con)
    moved = lab != -1
    n1, d1, n2, d2, D = S.nearest_two(X[moved], cids, cents)
    col = {c: k for k, c in enumerate(cids)}
    moved_ids = [r[0] for r, mv in zip(rows, moved) if mv]
    entries = []
    for k, (rid, own) in enumerate(zip(moved_ids, lab[moved])):
        own = int(own)
        e = (rid, own, float(D[k, col[own]]), int(n1[k]), float(d1[k]), int(n2[k]), float(d2[k]))
        con.execute("""UPDATE assignments SET status='clustered', cluster=?, distance=?,
                       nearest_cluster=?, nearest_distance=?, second_cluster=?, second_distance=?,
                       source='bucket_recluster', assigned_at=?, run_id=? WHERE review_id=?""",
                    (*e[1:], now, run_id, rid))
        entries.append(e)
    S.write_log(con, run_id, now, "bucket_recluster", entries)
    return len(found), int(moved.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--through", help="YYYY-MM-DD: only assign reviews dated on or before this day")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    con = sqlite3.connect(C.DB_PATH)
    S.ensure_schema(con)
    if not con.execute("SELECT COUNT(*) FROM centroids").fetchone()[0]:
        sys.exit("no centroids - run bootstrap_v2.py first")
    if args.reset:
        reset(con)
        return 0

    started = datetime.now().isoformat()
    bucket_before = con.execute("SELECT COUNT(*) FROM assignments WHERE status='unassigned'").fetchone()[0]
    run_id = con.execute("INSERT INTO assign_runs (started_at, status, threshold, bucket_before) "
                         "VALUES (?, 'running', ?, ?)",
                         (started, C.ASSIGNMENT_THRESHOLD, bucket_before)).lastrowid
    con.commit()
    try:
        q = """SELECT c.review_id, c.text, c.at FROM reviews_clean c
               LEFT JOIN assignments a USING (review_id) WHERE a.review_id IS NULL"""
        params = ()
        if args.through:
            end = date.fromisoformat(args.through) + timedelta(days=1)
            q += " AND c.at < ?"
            params = (end.isoformat(),)
        pending = con.execute(q + " ORDER BY c.at", params).fetchall()
        print(f"=== {started[:19]} assign run {run_id}: {len(pending)} reviews pending, "
              f"{C.DISTANCE_METRIC} threshold {C.ASSIGNMENT_THRESHOLD}, "
              f"bucket holds {bucket_before}")

        assigned = unassigned = new_clusters = reclustered = 0
        per_cluster = Counter()
        if pending:
            X = load_or_make_vectors(con, pending)
            cids, cents, _ = S.load_centroids(con)
            n1, d1, n2, d2, _ = S.nearest_two(X, cids, cents)
            ok = d1 < C.ASSIGNMENT_THRESHOLD
            con.executemany("INSERT INTO assignments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            [(p[0], "clustered" if a else "unassigned", int(c1) if a else None,
                              float(x1) if a else None, int(c1), float(x1), int(c2), float(x2),
                              "incremental", started, run_id)
                             for p, a, c1, x1, c2, x2 in zip(pending, ok, n1, d1, n2, d2)])
            S.write_log(con, run_id, started, "incremental",
                        [(p[0], int(c1) if a else None, float(x1) if a else None,
                          int(c1), float(x1), int(c2), float(x2))
                         for p, a, c1, x1, c2, x2 in zip(pending, ok, n1, d1, n2, d2)])
            gains = defaultdict(list)
            for v, a, c1 in zip(X, ok, n1):
                if a:
                    gains[int(c1)].append(v.astype(np.float64))
            if not C.FREEZE_CENTROIDS:
                update_centroids(con, gains, started)
            per_cluster = Counter({c: len(v) for c, v in gains.items()})
            assigned, unassigned = int(ok.sum()), int((~ok).sum())

        new_clusters, reclustered = recluster_bucket(con, run_id, started)
        bucket_after = con.execute("SELECT COUNT(*) FROM assignments WHERE status='unassigned'").fetchone()[0]
        con.execute("""UPDATE assign_runs SET finished_at=?, status='success', pending=?, assigned=?,
                       unassigned=?, bucket_after=?, new_clusters=?, reclustered=? WHERE run_id=?""",
                    (datetime.now().isoformat(), len(pending), assigned, unassigned, bucket_after,
                     new_clusters, reclustered, run_id))
        con.commit()
    except Exception as e:
        con.rollback()
        con.execute("UPDATE assign_runs SET finished_at=?, status='failed', error=? WHERE run_id=?",
                    (datetime.now().isoformat(), repr(e), run_id))
        con.commit()
        print(f"run {run_id} failed, nothing written: {e!r}")
        return 1

    print(f"\nassigned {assigned}, to bucket {unassigned}, "
          f"new clusters from bucket {new_clusters} ({reclustered} reviews moved)")
    if per_cluster:
        _, _, ns = S.load_centroids(con)
        print(f"\n{'cluster':>7}  {'+new':>4}  {'total':>5}  theme")
        for c, n in per_cluster.most_common():
            print(f"{c:>7}  {n:>4}  {ns[c]:>5}  {S.theme_label(c)}")
    print(f"\nunassigned bucket: {bucket_after} reviews")
    return 0


if __name__ == "__main__":
    sys.exit(main())

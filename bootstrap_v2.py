"""
One-time setup for incremental assignment (v2, phase 2).

v1's cluster.py never saved its fitted UMAP, so the 5-d space the clusters were found in only
existed in memory. This script:
  1. refits UMAP on emb.npy with v1's exact parameters and seed, and saves it to models/
  2. re-runs v1's HDBSCAN on it and checks the result reproduces the stored `clusters` table
     (refuses to continue if it doesn't - that would mean it's a different space)
  3. stores every v1 review's embedding and reduced vector
  4. computes one centroid per v1 cluster (from the stored labels, including split17's 100-106)
  5. records every v1 review in `assignments` with source='initial'
  6. prints diagnostics on distances in this space

Does not touch reviews_raw, reviews_clean or clusters.

    python bootstrap_v2.py            # refuses if already bootstrapped
    python bootstrap_v2.py --force    # wipe phase 2 tables and redo
"""
import argparse, os, sqlite3, sys
from datetime import datetime
import numpy as np

import config as C
import space as S


def pct(a):
    q = np.percentile(a, [10, 25, 50, 75, 90, 95, 99])
    return "  ".join(f"p{p}={v:.4f}" for p, v in zip([10, 25, 50, 75, 90, 95, 99], q)) + f"  max={a.max():.4f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    import umap, hdbscan, joblib
    from sklearn.metrics import adjusted_rand_score

    con = sqlite3.connect(C.DB_PATH)
    S.ensure_schema(con)
    if con.execute("SELECT COUNT(*) FROM centroids").fetchone()[0] and not args.force:
        sys.exit("already bootstrapped - use --force to redo (drops all phase 2 assignments)")

    emb = np.load(C.V1_EMBEDDINGS_FILE)
    rows = con.execute("SELECT review_id FROM reviews_clean ORDER BY rowid LIMIT ?",
                       (len(emb),)).fetchall()
    ids = [r[0] for r in rows]
    stored = dict(con.execute("SELECT review_id, cluster FROM clusters"))
    if set(ids) != set(stored):
        sys.exit("emb.npy rows do not line up with the clusters table - stopping")
    labels = np.array([stored[i] for i in ids])
    print(f"{len(ids)} v1 reviews, {len(set(labels)) - 1} v1 clusters, {(labels == -1).sum()} noise")

    print("fitting UMAP with v1 parameters (~2-3 min)...")
    reducer = umap.UMAP(n_components=C.UMAP_N_COMPONENTS, n_neighbors=C.UMAP_N_NEIGHBORS,
                        min_dist=C.UMAP_MIN_DIST, metric=C.UMAP_METRIC,
                        random_state=C.UMAP_RANDOM_STATE)
    red = reducer.fit_transform(emb)

    refit = hdbscan.HDBSCAN(min_cluster_size=C.HDBSCAN_MIN_CLUSTER_SIZE,
                            min_samples=C.HDBSCAN_MIN_SAMPLES, metric=C.HDBSCAN_METRIC,
                            cluster_selection_method=C.HDBSCAN_SELECTION).fit_predict(red)
    unsplit = np.where(labels >= C.V1_SPLIT_ID_START, C.V1_SPLIT_PARENT_CLUSTER, labels)
    both = (unsplit != -1) & (refit != -1)
    ari = adjusted_rand_score(unsplit[both], refit[both])
    print(f"reproduction check: ARI {ari:.4f} on {both.sum()} reviews clustered in both "
          f"(refit: {len(set(refit)) - 1} clusters, {(refit == -1).sum()} noise)")
    if ari < C.REPRODUCTION_MIN_ARI:
        sys.exit(f"ARI below REPRODUCTION_MIN_ARI={C.REPRODUCTION_MIN_ARI}: refit is not v1's space")

    os.makedirs(C.MODEL_DIR, exist_ok=True)
    joblib.dump(reducer, S.umap_path())
    print(f"saved {S.umap_path()}")

    now = datetime.now().isoformat()
    with con:
        for t in ("review_vectors", "centroids", "assignments", "assign_runs"):
            con.execute(f"DELETE FROM {t}")
        con.executemany("INSERT INTO review_vectors VALUES (?,?,?)",
                        [(i, S.to_blob(e), S.to_blob(r)) for i, e, r in zip(ids, emb, red)])

        cids = sorted(c for c in set(labels) if c != -1)
        cents = np.stack([red[labels == c].mean(axis=0) for c in cids])
        con.executemany("INSERT INTO centroids VALUES (?,?,?,?,?,?,NULL)",
                        [(int(c), S.to_blob(v), int((labels == c).sum()), "initial", now, now)
                         for c, v in zip(cids, cents)])

        n1, d1, n2, d2, D = S.nearest_two(red, cids, cents)
        col = {c: k for k, c in enumerate(cids)}
        recs = []
        for k, rid in enumerate(ids):
            c = int(labels[k])
            member = c != -1
            recs.append((rid, "clustered" if member else "noise", c if member else None,
                         float(D[k, col[c]]) if member else None,
                         int(n1[k]), float(d1[k]), int(n2[k]), float(d2[k]), "initial", now, None))
        con.executemany("INSERT INTO assignments VALUES (?,?,?,?,?,?,?,?,?,?,?)", recs)

    # ---------- diagnostics ----------
    m = labels != -1
    own = np.array([r[3] for r in recs if r[3] is not None])
    print("\n--- distances in the v1 space (cosine, 0 = identical direction) ---")
    print("v1 members -> own centroid:      ", pct(own))
    print("v1 noise   -> nearest centroid:  ", pct(d1[~m]))
    print("v1 members: nearest - own gap to 2nd:", pct((d2 - d1)[m]))

    agree_cos = (n1[m] == labels[m]).mean()
    E = np.linalg.norm(red[m][:, None, :] - cents[None, :, :], axis=2)
    agree_euc = (np.array(cids)[E.argmin(1)] == labels[m]).mean()
    print(f"\nv1 members whose nearest centroid is their own cluster: "
          f"cosine {agree_cos:.1%}   euclidean {agree_euc:.1%}")

    rng = np.random.default_rng(C.ROUNDTRIP_SEED)
    idx = rng.choice(np.flatnonzero(m), size=min(C.ROUNDTRIP_SAMPLE, m.sum()), replace=False)
    red_t = reducer.transform(emb[idx])
    t1, td1, _, _, _ = S.nearest_two(red_t, cids, cents)
    print(f"round trip: {len(idx)} v1 members re-projected with transform() as if new -> "
          f"nearest centroid is own cluster {np.mean(t1 == labels[idx]):.1%}")
    print("   their distance to nearest centroid:", pct(td1))
    print(f"   shift between fit and transform position (euclidean): "
          f"median {np.median(np.linalg.norm(red_t - red[idx], axis=1)):.3f}")
    print(f"\nASSIGNMENT_THRESHOLD is currently {C.ASSIGNMENT_THRESHOLD} (placeholder)")
    print(f"   {np.mean(own < C.ASSIGNMENT_THRESHOLD):.1%} of v1 members sit under it")
    con.close()


if __name__ == "__main__":
    main()

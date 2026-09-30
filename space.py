"""
Shared v2 plumbing: v1's embedding model, the saved v1 UMAP, distances to centroids,
and the tables phase 2 adds. Used by bootstrap_v2.py and assign.py.
"""
import os
import numpy as np
import config as C

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS review_vectors (
        review_id TEXT PRIMARY KEY,
        emb       BLOB,     -- 384 float32, MiniLM
        red       BLOB      -- 5 float32, v1 UMAP space
    )""",
    """CREATE TABLE IF NOT EXISTS centroids (
        cluster     INTEGER PRIMARY KEY,
        vec         BLOB,     -- mean of members' reduced vectors
        n_members   INTEGER,
        origin      TEXT,     -- initial | bucket_recluster
        created_at  TEXT,
        updated_at  TEXT,
        created_run INTEGER   -- assign_runs.run_id, NULL for initial
    )""",
    """CREATE TABLE IF NOT EXISTS assignments (
        review_id        TEXT PRIMARY KEY,
        status           TEXT,     -- clustered | noise (v1 noise) | unassigned (bucket)
        cluster          INTEGER,  -- NULL unless clustered
        distance         REAL,     -- to own centroid (config.DISTANCE_METRIC), at assignment time
        nearest_cluster  INTEGER,
        nearest_distance REAL,
        second_cluster   INTEGER,
        second_distance  REAL,
        source           TEXT,     -- initial | incremental | bucket_recluster
        assigned_at      TEXT,
        run_id           INTEGER   -- assign_runs.run_id, NULL for initial
    )""",
    """CREATE TABLE IF NOT EXISTS assign_runs (
        run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at    TEXT,
        finished_at   TEXT,
        status        TEXT,     -- running | success | failed | reset
        threshold     REAL,
        pending       INTEGER,
        assigned      INTEGER,
        unassigned    INTEGER,
        bucket_before INTEGER,
        bucket_after  INTEGER,
        new_clusters  INTEGER,
        reclustered   INTEGER,  -- bucket reviews moved into new clusters
        error         TEXT
    )""",
    # Append-only history of every assignment decision. Never deleted, not even by --reset,
    # so flags on it survive threshold changes.
    """CREATE TABLE IF NOT EXISTS assignment_log (
        log_id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id           INTEGER,
        logged_at        TEXT,
        review_id        TEXT,
        event            TEXT,     -- incremental | bucket_recluster
        outcome          TEXT,     -- assigned | unassigned
        cluster          INTEGER,  -- NULL when unassigned
        cluster_label    TEXT,     -- themes.py name at log time
        distance         REAL,     -- to own centroid (= nearest for incremental)
        nearest_cluster  INTEGER,
        nearest_label    TEXT,
        nearest_distance REAL,
        second_cluster   INTEGER,
        second_label     TEXT,
        second_distance  REAL,
        gap              REAL,     -- second_distance - nearest_distance
        threshold        REAL
    )""",
    """CREATE TABLE IF NOT EXISTS assignment_flags (
        log_id          INTEGER PRIMARY KEY,   -- assignment_log.log_id
        review_id       TEXT,
        flagged_at      TEXT,
        verdict         TEXT,     -- wrong
        correct_cluster TEXT,     -- cluster id, 'bucket', or NULL if unknown
        note            TEXT
    )""",
]


def write_log(con, run_id, now, event, entries):
    """entries: (review_id, cluster or None, distance or None, n1, d1, n2, d2)"""
    con.executemany(
        """INSERT INTO assignment_log (run_id, logged_at, review_id, event, outcome, cluster,
           cluster_label, distance, nearest_cluster, nearest_label, nearest_distance,
           second_cluster, second_label, second_distance, gap, threshold, metric)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(run_id, now, rid, event, "assigned" if c is not None else "unassigned", c,
          theme_label(c) if c is not None else None, dist, n1, theme_label(n1), d1,
          n2, theme_label(n2), d2, d2 - d1, C.ASSIGNMENT_THRESHOLD, C.DISTANCE_METRIC)
         for rid, c, dist, n1, d1, n2, d2 in entries])


def ensure_schema(con):
    for s in SCHEMA:
        con.execute(s)
    # added after the first logged runs, which were all cosine
    cols = [r[1] for r in con.execute("PRAGMA table_info(assignment_log)")]
    if "metric" not in cols:
        con.execute("ALTER TABLE assignment_log ADD COLUMN metric TEXT")
        con.execute("UPDATE assignment_log SET metric = 'cosine'")
        con.commit()


def to_blob(v):
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b):
    return np.frombuffer(b, dtype=np.float32)


def umap_path():
    return os.path.join(C.MODEL_DIR, C.UMAP_MODEL_FILE)


_model = None
def embed(texts):
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(C.EMBEDDING_MODEL)
    return _model.encode(texts, batch_size=C.EMBED_BATCH_SIZE, show_progress_bar=False)


def load_reducer():
    import joblib
    return joblib.load(umap_path())


def cosine_distances(X, cents):
    """X: (n, d), cents: (k, d) -> (n, k) cosine distances.
    float64 because distances in the UMAP space are ~1e-4 and float32 rounding shows at that scale."""
    X, cents = np.asarray(X, np.float64), np.asarray(cents, np.float64)
    Xn = X / np.linalg.norm(X, axis=1, keepdims=True)
    Cn = cents / np.linalg.norm(cents, axis=1, keepdims=True)
    return 1.0 - Xn @ Cn.T


def euclidean_distances(X, cents):
    """X: (n, d), cents: (k, d) -> (n, k) straight-line distances (HDBSCAN's metric in v1)."""
    X, cents = np.asarray(X, np.float64), np.asarray(cents, np.float64)
    return np.linalg.norm(X[:, None, :] - cents[None, :, :], axis=2)


METRICS = {"cosine": cosine_distances, "euclidean": euclidean_distances}


def distances(X, cents):
    return METRICS[C.DISTANCE_METRIC](X, cents)


def nearest_two(X, cent_ids, cents):
    """Per row: (nearest id, its distance, second id, its distance), in C.DISTANCE_METRIC."""
    D = distances(X, cents)
    order = np.argsort(D, axis=1)
    rows = np.arange(len(X))
    i1, i2 = order[:, 0], order[:, 1]
    ids = np.asarray(cent_ids)
    return ids[i1], D[rows, i1], ids[i2], D[rows, i2], D


def load_centroids(con):
    rows = con.execute("SELECT cluster, vec, n_members FROM centroids ORDER BY cluster").fetchall()
    ids = [r[0] for r in rows]
    vecs = np.stack([from_blob(r[1]) for r in rows]) if rows else np.zeros((0, C.UMAP_N_COMPONENTS))
    ns = {r[0]: r[2] for r in rows}
    return ids, vecs, ns


def theme_label(cluster):
    from themes import THEMES
    if cluster is None:
        return "(unassigned)"
    return THEMES.get(cluster, "(unnamed cluster - not in themes.py)")

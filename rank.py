"""
Daily ranking snapshot (v2, phase 4). Run after assign.py.

Ranks clusters by total review count (v1 members + every review assigned since), descending.
Tied totals share a rank (1, 2, 2, 4), so a tie can't show up as fake movement;
display order within a tie is by cluster id. Recency is not part of the rank.
No severity weighting (ruled out in v1).

Two ranked groups, because themes.py is v1's list of complaint themes:
    theme  - clusters named in themes.py (the complaint ranking)
    other  - clusters v1 left out of themes.py (praise, language, general anger) and any
             clusters found in the unassigned bucket
Each snapshot is keyed to the latest assign run and compared with the previous snapshot:
movement is up / down / same / new. The bucket size is stored alongside (grp 'bucket').

Themes (themes_v2.json) are ranked the same way in theme_rank_snapshots: complaint themes
ranked among themselves by total reviews; other groups (separate, positive, unsorted) get a
total but no rank.

    python rank.py              # snapshot the latest assign run
    python rank.py --backfill   # theme snapshots for every run since the last reset, rebuilt
                                # from assignments (a clustered review counts from its run_id on)
"""
import argparse, sqlite3, sys
from datetime import datetime

import config as C
from themes import THEMES
import taxonomy

SCHEMA = """CREATE TABLE IF NOT EXISTS rank_snapshots (
    run_id    INTEGER,   -- assign_runs.run_id this snapshot describes
    taken_at  TEXT,
    cluster   INTEGER,   -- NULL for the bucket row
    grp       TEXT,      -- theme | other | bucket
    total     INTEGER,
    rank      INTEGER,   -- within grp; NULL for bucket
    prev_rank INTEGER,
    movement  TEXT,      -- up | down | same | new
    PRIMARY KEY (run_id, grp, cluster)
)"""

THEME_SCHEMA = """CREATE TABLE IF NOT EXISTS theme_rank_snapshots (
    run_id    INTEGER,
    taken_at  TEXT,
    theme     TEXT,      -- themes_v2.json key
    kind      TEXT,      -- complaint | separate | positive | unsorted
    total     INTEGER,
    rank      INTEGER,   -- complaint themes only
    prev_rank INTEGER,
    movement  TEXT,      -- up | down | same | new (complaint themes only)
    PRIMARY KEY (run_id, theme)
)"""


def cluster_totals_at(con, run_id):
    """Cluster sizes as they stood after run_id: v1 members plus reviews clustered by then."""
    return con.execute("""SELECT cluster, COUNT(*) FROM assignments WHERE status = 'clustered'
                          AND (source = 'initial' OR run_id <= ?) GROUP BY cluster""", (run_id,)).fetchall()


def snapshot_themes(con, run_id, totals, now):
    themes, clusters = taxonomy.load([c for c, _ in totals])
    by_theme = {k: 0 for k in themes}
    for c, n in totals:
        by_theme[clusters[c]["theme"]] += n
    prev_run = con.execute("SELECT MAX(run_id) FROM theme_rank_snapshots WHERE run_id < ?",
                           (run_id,)).fetchone()[0]
    prev = dict(con.execute("SELECT theme, rank FROM theme_rank_snapshots WHERE run_id = ?", (prev_run,)))
    comp = {k: n for k, n in by_theme.items() if themes[k]["kind"] == "complaint"}
    rows = []
    for k, n in by_theme.items():
        rank = p = move = None
        if k in comp:
            rank = 1 + sum(m > n for m in comp.values())
            p = prev.get(k)
            move = "new" if p is None else "up" if rank < p else "down" if rank > p else "same"
        rows.append((run_id, now, k, themes[k]["kind"], n, rank, p, move))
    con.execute("DELETE FROM theme_rank_snapshots WHERE run_id = ?", (run_id,))
    con.executemany("INSERT INTO theme_rank_snapshots VALUES (?,?,?,?,?,?,?,?)", rows)
    return rows


def backfill(con):
    last_reset = con.execute("SELECT MAX(run_id) FROM assign_runs WHERE status='reset'").fetchone()[0]
    runs = [r for (r,) in con.execute("SELECT run_id FROM assign_runs WHERE run_id >= ? "
                                      "AND status IN ('success','reset') ORDER BY run_id", (last_reset,))]
    now = datetime.now().isoformat(timespec="seconds")
    with con:
        con.execute("DELETE FROM theme_rank_snapshots WHERE run_id >= ?", (last_reset,))
        for r in runs:
            snapshot_themes(con, r, cluster_totals_at(con, r), now)
    print(f"theme snapshots rebuilt for {len(runs)} runs ({runs[0]}-{runs[-1]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(C.DB_PATH)
    con.execute(SCHEMA)
    con.execute(THEME_SCHEMA)
    if args.backfill:
        return backfill(con)
    run_id = con.execute("SELECT MAX(run_id) FROM assign_runs WHERE status IN ('success','reset')").fetchone()[0]
    if run_id is None:
        sys.exit("no assign runs yet")
    prev_run = con.execute("SELECT MAX(run_id) FROM rank_snapshots WHERE run_id < ?", (run_id,)).fetchone()[0]
    prev = {(g, c): r for g, c, r in con.execute(
        "SELECT grp, cluster, rank FROM rank_snapshots WHERE run_id = ?", (prev_run,))}

    totals = con.execute("""SELECT cluster, COUNT(*) FROM assignments WHERE status = 'clustered'
                            GROUP BY cluster""").fetchall()
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for grp in ("theme", "other"):
        members = sorted(((c, n) for c, n in totals if (c in THEMES) == (grp == "theme")),
                         key=lambda x: (-x[1], x[0]))
        for c, n in members:
            rank = 1 + sum(m > n for _, m in members)   # ties share a rank (1, 2, 2, 4)
            p = prev.get((grp, c))
            move = "new" if p is None else "up" if rank < p else "down" if rank > p else "same"
            rows.append((run_id, now, c, grp, n, rank, p, move))
    bucket = con.execute("SELECT COUNT(*) FROM assignments WHERE status = 'unassigned'").fetchone()[0]
    rows.append((run_id, now, None, "bucket", bucket, None, None, None))

    with con:
        con.execute("DELETE FROM rank_snapshots WHERE run_id = ?", (run_id,))
        con.executemany("INSERT INTO rank_snapshots VALUES (?,?,?,?,?,?,?,?)", rows)
        trows = snapshot_themes(con, run_id, totals, now)
    moved = [r for r in rows if r[7] in ("up", "down", "new")]
    print(f"rank snapshot for assign run {run_id} (previous: {prev_run}): "
          f"{len(rows) - 1} clusters, bucket {bucket}, {len(moved)} moved or new")
    for r in moved:
        print(f"   [{r[3]}] cluster {r[2]}: {r[6]} -> {r[5]} ({r[7]})")
    for r in trows:
        if r[7] in ("up", "down", "new"):
            print(f"   [theme] {r[2]}: {r[6]} -> {r[5]} ({r[7]})")


if __name__ == "__main__":
    main()

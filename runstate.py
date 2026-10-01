"""
Run bookkeeping shared by daily_ingest.py and assign.py.

A run row is written as 'running' when a run starts and updated when it ends. If the process is
stopped from outside (window closed, killed) it may never get to update its row. The next run
calls mark_abandoned() first, which turns any 'running' row older than RUN_STALE_HOURS into
'failed', so a stopped run can't look like it's still going.
"""
from datetime import datetime, timedelta

import config as C


def mark_abandoned(con, table):
    cutoff = (datetime.now() - timedelta(hours=C.RUN_STALE_HOURS)).isoformat()
    n = con.execute(f"""UPDATE {table} SET status = 'failed', finished_at = ?,
                        error = 'abandoned: still running when a later run started (process stopped without recording)'
                        WHERE status = 'running' AND started_at < ?""",
                    (datetime.now().isoformat(), cutoff)).rowcount
    con.commit()
    return n

"""
VoC Copilot local web app (v2, phase 4). Flask, localhost only.

Step 1: one page, "/", the theme dashboard built live from reviews.db on every request,
so it always shows the latest run without rebuilding dashboard_v2.html. Reads only.
Later steps add more read-only views and two small writes (flags, labels).

    python app.py        # then open http://127.0.0.1:5000/
Stop it with Ctrl+C.
"""
import sqlite3
from flask import Flask

import config as C
import dashboard_v2

app = Flask(__name__)


def read_con():
    """A connection that can't write: query_only makes SQLite refuse INSERT/UPDATE/DELETE.
    reviews.db is in WAL mode, so reading never blocks the daily job's writes, and if the job
    is mid-commit the request waits up to DB_BUSY_TIMEOUT_S instead of failing."""
    con = sqlite3.connect(C.DB_PATH, timeout=C.DB_BUSY_TIMEOUT_S)
    con.execute("PRAGMA query_only = ON")
    return con


@app.get("/")
def dashboard():
    """The theme dashboard, same page as dashboard_v2.html but read fresh from reviews.db."""
    con = read_con()
    try:
        payload, _ = dashboard_v2.build_payload(con)
    finally:
        con.close()
    return dashboard_v2.render_html(payload)


if __name__ == "__main__":
    app.run(host=C.APP_HOST, port=C.APP_PORT, debug=False)

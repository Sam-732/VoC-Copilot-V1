"""
VoC Copilot local web app (v2, phase 4). Flask, localhost only.

Every page is built live from reviews.db on each visit, through a connection that can't write.

    python app.py        # then open http://127.0.0.1:5000/
Stop it with Ctrl+C.

Pages (step 2 - all read-only):
    /          the theme dashboard (same page as dashboard_v2.html)
    /trends    rank after each run, reviews per day per theme, bucket size over time
    /bucket    clusters found in the bucket, and every unassigned review
    /search    search the text of every review
    /runs      every ingest run and assign run
"""
import re
import sqlite3
from flask import Flask, render_template, render_template_string, request
from markupsafe import Markup, escape

import charts
import config as C
import dashboard_v2
import queries

app = Flask(__name__)


def read_con():
    """A connection that can't write: query_only makes SQLite refuse INSERT/UPDATE/DELETE.
    reviews.db is in WAL mode, so reading never blocks the daily job's writes, and if the job
    is mid-commit the request waits up to DB_BUSY_TIMEOUT_S instead of failing."""
    con = sqlite3.connect(C.DB_PATH, timeout=C.DB_BUSY_TIMEOUT_S)
    con.execute("PRAGMA query_only = ON")
    return con


def with_con(fn, *args):
    con = read_con()
    try:
        return fn(con, *args)
    finally:
        con.close()


@app.context_processor
def shared():
    """Available in every template: the dashboard's styling and the bar-chart helper."""
    return {"style": dashboard_v2.STYLE, "bars": charts.daily_bars}


@app.template_filter("highlight")
def highlight(text, q):
    """Escape the review text first, then wrap each match of q in <mark>, ignoring case."""
    safe = str(escape(text))
    if not q:
        return Markup(safe)
    return Markup(re.sub("(" + re.escape(str(escape(q))) + ")", r"<mark>\1</mark>", safe, flags=re.I))


def nav(active):
    return render_template_string('{% include "_nav.html" %}', active=active)


@app.get("/")
def dashboard():
    """The theme dashboard, same page as dashboard_v2.html but read fresh from reviews.db."""
    payload, _ = with_con(dashboard_v2.build_payload)
    return dashboard_v2.render_html(payload, nav=nav("/"))


@app.get("/trends")
def trends():
    """Rank after each run, reviews per day for each complaint theme, bucket size over time."""
    return render_template("trends.html", active="/trends", title="Trends",
                           intro="How the complaint themes and the unassigned bucket have moved, day by day and run by run.",
                           t=with_con(queries.trends))


@app.get("/bucket")
def bucket():
    """Clusters found in the bucket, then every unassigned review (sortable)."""
    sort = request.args.get("sort", "distance")
    if sort not in ("distance", "date", "helpful"):
        sort = "distance"
    return render_template("bucket.html", active="/bucket", title="Bucket",
                           intro="Reviews that fit no existing cluster, and the clusters found among them.",
                           b=with_con(queries.bucket, sort))


@app.get("/search")
def search():
    """Search the raw text of every review, and show where each match sits now."""
    return render_template("search.html", active="/search", title="Search",
                           intro="Every stored review, including ones never clustered.",
                           s=with_con(queries.search, request.args.get("q", "")),
                           min_chars=C.SEARCH_MIN_CHARS)


@app.get("/runs")
def runs():
    """Every ingest run (fetching reviews) and every assign run (placing them)."""
    return render_template("runs.html", active="/runs", title="Runs",
                           intro="What each daily run did, including failures and anomalies.",
                           r=with_con(queries.runs))


if __name__ == "__main__":
    app.run(host=C.APP_HOST, port=C.APP_PORT, debug=False)

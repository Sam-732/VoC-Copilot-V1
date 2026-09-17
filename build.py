import sqlite3, collections, html
from themes import THEMES

con = sqlite3.connect("reviews.db")
rows = con.execute("""
    SELECT c.cluster, r.review_id, r.content, r.score, r.at, r.thumbs_up
    FROM clusters c JOIN reviews_raw r ON r.review_id = c.review_id
    WHERE c.cluster != -1
""").fetchall()
con.close()

themes = collections.defaultdict(list)
for cid, rid, text, score, at, thumbs in rows:
    if cid in THEMES:
        themes[THEMES[cid]].append((rid, text, score, at, thumbs or 0))

ordered = sorted(themes.items(), key=lambda x: -len(x[1]))
total = sum(len(v) for _, v in ordered)

parts = ["""<meta charset="utf-8"><title>Swiggy complaint themes</title><style>
body{font-family:system-ui,sans-serif;max-width:860px;margin:40px auto;padding:0 20px;
     line-height:1.55;color:#1a1a1a;background:#fafafa}
h1{margin-bottom:4px} .sub{color:#666;margin-bottom:36px;font-size:15px}
.theme{background:#fff;border:1px solid #e2e2e2;border-radius:4px;padding:20px 24px;margin-bottom:20px}
.rank{color:#999;font-size:13px;font-family:monospace}
h2{font-size:19px;margin:6px 0 10px}
.meta{font-size:13px;color:#666;margin-bottom:14px;font-family:monospace}
.rev{border-left:3px solid #ddd;padding:6px 0 6px 14px;margin:12px 0;font-size:14px}
.stars{color:#c0392b;font-weight:600} .date{color:#999;font-size:12px}
</style>"""]

parts.append(f"<h1>Swiggy - complaint themes</h1>")
parts.append(f"<p class='sub'>Play Store, India, 16 Aug - 15 Sep 2026. "
             f"13,000 reviews collected, {total:,} sorted into {len(ordered)} themes. "
             f"Ranked by number of reviews. Every review below is verbatim.</p>")

for i, (name, revs) in enumerate(ordered, 1):
    revs.sort(key=lambda r: -r[4])
    avg = sum(r[2] for r in revs) / len(revs)
    dates = sorted(r[3] for r in revs)
    parts.append(f"<div class='theme'><div class='rank'>#{i}</div><h2>{html.escape(name)}</h2>")
    parts.append(f"<div class='meta'>{len(revs)} reviews &middot; mean {avg:.1f} stars "
                 f"&middot; {dates[0][:10]} to {dates[-1][:10]}</div>")
    for rid, text, score, at, thumbs in revs[:12]:
        up = f" &middot; {thumbs} found helpful" if thumbs else ""
        parts.append(f"<div class='rev'><span class='stars'>{'*' * score}</span> "
                     f"<span class='date'>{at[:10]}{up}</span><br>{html.escape(text)}</div>")
    if len(revs) > 12:
        parts.append(f"<div class='date'>+ {len(revs)-12} more</div>")
    parts.append("</div>")

open("themes.html", "w", encoding="utf-8").write("\n".join(parts))
print(f"wrote themes.html - {len(ordered)} themes, {total} reviews")
"""
Builds a single self-contained dashboard.html from reviews.db.
No internet, no libraries - open the file in any browser, or host it on GitHub Pages.
"""
import sqlite3, json, re, collections, html
from themes import THEMES

DB = "reviews.db"

SIGNALS = {
    "delay / late":      r"late|delay|hour|hrs|mint|minut|der[ií]|ghant",
    "cancellation":      r"cancel",
    "fees / charges":    r"\bfee|charge|surge|\btax|gst|platform fee",
    "refund":            r"refund|paisa wapas|money back",
    "support / chatbot": r"\bbot\b|chatbot|\bai\b|human agent|executive|customer care|customer support",
    "distance / km":     r"\b\d+\s?k ?m\b|distance|kilomet|google maps",
}

con = sqlite3.connect(DB)
n_raw   = con.execute("SELECT COUNT(*) FROM reviews_raw").fetchone()[0]
n_clean = con.execute("SELECT COUNT(*) FROM reviews_clean").fetchone()[0]
rows = con.execute("""
    SELECT c.cluster, r.review_id, r.content, r.score, r.at, r.thumbs_up
    FROM clusters c JOIN reviews_raw r ON r.review_id = c.review_id
    WHERE c.cluster != -1
""").fetchall()
con.close()

# ---- group into themes -------------------------------------------------
themes = collections.defaultdict(lambda: {"reviews": [], "clusters": set()})
for cid, rid, text, score, at, thumbs in rows:
    if cid not in THEMES:
        continue
    t = themes[THEMES[cid]]
    t["clusters"].add(cid)
    t["reviews"].append({
        "id": rid, "t": text or "", "s": score,
        "d": (at or "")[:10], "u": thumbs or 0,
    })

data = []
for name, t in themes.items():
    revs = sorted(t["reviews"], key=lambda r: -r["u"])
    data.append({
        "name": name,
        "clusters": sorted(t["clusters"]),
        "n": len(revs),
        "votes": sum(r["u"] for r in revs),
        "mean": round(sum(r["s"] for r in revs) / len(revs), 1),
        "from": min(r["d"] for r in revs),
        "to": max(r["d"] for r in revs),
        "reviews": revs,
    })
data.sort(key=lambda d: -d["n"])
n_themed = sum(d["n"] for d in data)

# ---- cross-cutting signal counts ---------------------------------------
all_text = [(THEMES[c], txt or "") for c, _, txt, _, _, _ in rows if c in THEMES]
signals = []
for label, pat in SIGNALS.items():
    rx = re.compile(pat, re.I)
    hits = [th for th, txt in all_text if rx.search(txt)]
    top = collections.Counter(hits).most_common(1)
    signals.append({
        "label": label,
        "n": len(hits),
        "pct": round(len(hits) / max(n_themed, 1) * 100),
        "top": top[0][0] if top else "",
    })
signals.sort(key=lambda s: -s["n"])

payload = {
    "funnel": {"raw": n_raw, "clean": n_clean, "themed": n_themed},
    "themes": data,
    "signals": signals,
}

TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Swiggy Voice of Customer</title>
<style>
:root{
  --bg:#f4f6f5; --surface:#fff; --ink:#131a19; --muted:#5c6a66; --faint:#8d9b97;
  --rule:#e0e7e5; --rule-soft:#edf2f1; --accent:#0e6a66; --accent-soft:#cfe5e3;
  --warn:#8a5a14; --flag:#9c3a20;
  --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#0d1312; --surface:#141c1b; --ink:#e6ecea; --muted:#9aa8a4; --faint:#6e7b78;
  --rule:#26312f; --rule-soft:#1c2524; --accent:#5cc0b7; --accent-soft:#1b3835;
  --warn:#d6b25e; --flag:#e08f74;
}}
:root[data-theme=dark]{
  --bg:#0d1312; --surface:#141c1b; --ink:#e6ecea; --muted:#9aa8a4; --faint:#6e7b78;
  --rule:#26312f; --rule-soft:#1c2524; --accent:#5cc0b7; --accent-soft:#1b3835;
  --warn:#d6b25e; --flag:#e08f74;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
     font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1000px;margin:0 auto;padding-inline:20px;padding-block:40px 80px}

header{border-bottom:2px solid var(--ink);padding-bottom:22px;margin-bottom:28px}
h1{margin:0 0 6px;font-size:clamp(1.7rem,4vw,2.3rem);letter-spacing:-.02em}
.scope{color:var(--muted);font-size:14px;margin:0;max-width:65ch}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:26px 0}
.tile{background:var(--surface);border:1px solid var(--rule);border-radius:3px;padding:14px 16px}
.tile .v{font-size:1.75rem;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.tile .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;
         color:var(--faint);margin-top:2px}
.tile .n{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.35}

.caveat{border-left:3px solid var(--warn);background:var(--surface);padding:12px 16px;
        font-size:13.5px;color:var(--muted);margin-bottom:26px}
.caveat b{color:var(--ink);font-weight:600}

h2{font-size:12px;font-family:var(--mono);letter-spacing:.1em;text-transform:uppercase;
   color:var(--faint);margin:34px 0 12px;font-weight:500}

table{width:100%;border-collapse:collapse;background:var(--surface);
      border:1px solid var(--rule);border-radius:3px;font-size:13.5px}
th{font-family:var(--mono);font-size:10px;letter-spacing:.09em;text-transform:uppercase;
   color:var(--faint);text-align:left;padding:9px 14px;border-bottom:1px solid var(--rule);font-weight:500}
td{padding:9px 14px;border-bottom:1px solid var(--rule-soft);vertical-align:middle}
tbody tr:last-child td{border-bottom:none}
td.num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.track{height:7px;background:var(--rule-soft);border-radius:4px;overflow:hidden;min-width:60px}
.track i{display:block;height:100%;background:var(--accent);border-radius:4px}

.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:26px 0 16px}
input[type=search]{flex:1;min-width:210px;padding:9px 12px;font:inherit;font-size:14px;
  background:var(--surface);color:var(--ink);border:1px solid var(--rule);border-radius:3px}
input[type=search]:focus{outline:2px solid var(--accent);outline-offset:1px}
.seg{display:flex;border:1px solid var(--rule);border-radius:3px;overflow:hidden}
.seg button{font:inherit;font-size:12.5px;padding:8px 13px;border:0;cursor:pointer;
  background:var(--surface);color:var(--muted)}
.seg button[aria-pressed=true]{background:var(--accent);color:var(--bg);font-weight:600}
.seg button:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.hits{font-family:var(--mono);font-size:12px;color:var(--faint)}

.theme{background:var(--surface);border:1px solid var(--rule);border-radius:3px;margin-bottom:12px}
.thead{display:grid;grid-template-columns:34px 1fr auto;gap:14px;align-items:baseline;
       padding:15px 18px;cursor:pointer}
.thead:hover{background:var(--rule-soft)}
.rk{font-family:var(--mono);font-size:12px;color:var(--faint)}
.tname{font-size:16.5px;font-weight:600;margin:0 0 5px;line-height:1.3}
.tmeta{font-family:var(--mono);font-size:11.5px;color:var(--muted);
       display:flex;flex-wrap:wrap;gap:4px 14px}
.chev{color:var(--faint);font-size:13px;font-family:var(--mono)}
.body{display:none;border-top:1px solid var(--rule);padding:6px 18px 16px}
.theme.open .body{display:block}

.rev{border-left:3px solid var(--rule);padding:8px 0 8px 14px;margin:14px 0;font-size:13.5px}
.rev.up{border-left-color:var(--accent)}
.rmeta{font-family:var(--mono);font-size:11px;color:var(--faint);
       margin-bottom:4px;display:flex;flex-wrap:wrap;gap:4px 12px}
.stars{color:var(--flag);font-weight:600;letter-spacing:1px}
.votes{color:var(--accent);font-weight:500}
.rid{opacity:.6}
mark{background:var(--accent-soft);color:var(--ink);padding:0 1px;border-radius:2px}
.more{font-family:var(--mono);font-size:11.5px;color:var(--faint);margin-top:10px}
.empty{color:var(--muted);font-size:14px;padding:22px 0}

footer{margin-top:44px;padding-top:20px;border-top:1px solid var(--rule);
       font-family:var(--mono);font-size:11.5px;color:var(--faint);line-height:1.7;max-width:76ch}
@media (max-width:560px){
  .thead{grid-template-columns:26px 1fr;gap:8px}
  .chev{display:none}
  .wrap{padding-block:28px 60px}
}
</style></head><body>
<div class="wrap">

<header>
  <h1>Swiggy — Voice of Customer</h1>
  <p class="scope">Google Play Store reviews, India, 16 Aug – 15 Sep 2026. Complaint themes found by
  clustering review text, named by hand, ranked by how many reviews each contains. Every review shown
  is verbatim and unedited.</p>
</header>

<div class="tiles" id="tiles"></div>

<div class="caveat">
  <b>What these numbers are not.</b> Reviewers are a self-selected, mostly angry minority of users —
  this measures what people complain about publicly, not what users think. Theme sizes count each
  review once under its dominant complaint, so secondary complaints are undercounted; the signal
  table below is the correction. Agreement between the clustering and a hand-labelled set of
  182 reviews was <b>21%</b> — themes are a starting point for investigation, not a verdict.
</div>

<h2>Signals across all themes</h2>
<p class="scope" style="margin:-4px 0 12px;font-size:13px">Keyword counts, independent of clustering.
A review mentioning several of these is counted in each — this is how a complaint that is usually
someone's <em>second</em> problem becomes visible.</p>
<table id="sigtable"><thead><tr>
  <th>Signal</th><th>Share of themed reviews</th><th class="num">Reviews</th><th>Most often in</th>
</tr></thead><tbody></tbody></table>

<h2>Complaint themes</h2>
<div class="controls">
  <input type="search" id="q" placeholder="Search all reviews — try refund, bot, cancel, biryani…"
         autocomplete="off" spellcheck="false">
  <div class="seg" role="group" aria-label="Sort themes by">
    <button id="byN" aria-pressed="true">By reviews</button>
    <button id="byV" aria-pressed="false">By helpful votes</button>
  </div>
  <span class="hits" id="hits"></span>
</div>
<div id="themes"></div>

<footer>
  Built from 13,000 Play Store reviews scraped with google-play-scraper, stored append-only in SQLite,
  embedded with paraphrase-multilingual-MiniLM-L12-v2, reduced with UMAP and clustered with HDBSCAN.
  Cluster IDs on each theme trace back to the raw table, so every claim here resolves to an unmodified
  source review. Play Store exposes no public URL for an individual review, so citation means the
  verbatim text, rating and date rather than a link.
</footer>

</div>
<script id="payload" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('payload').textContent);
const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = n => n.toLocaleString('en-IN');
let sortKey = 'n', query = '';

const tiles = [
  ['raw','Reviews collected','30 days of Play Store reviews, stored untouched'],
  ['clean','With real content','after dropping the 4-word-or-shorter ones ("good", "worst")'],
  ['themed','Inside a theme','the rest did not fit any theme and were left out'],
];
document.getElementById('tiles').innerHTML = tiles.map(([k,label,note]) =>
  `<div class="tile"><div class="v">${fmt(D.funnel[k])}</div>
   <div class="k">${label}</div><div class="n">${note}</div></div>`).join('');

const sigMax = Math.max(...D.signals.map(s => s.n));
document.querySelector('#sigtable tbody').innerHTML = D.signals.map(s =>
  `<tr><td>${esc(s.label)}</td>
   <td><div class="track"><i style="width:${(s.n/sigMax*100).toFixed(1)}%"></i></div></td>
   <td class="num">${fmt(s.n)} <span style="color:var(--faint)">(${s.pct}%)</span></td>
   <td style="color:var(--muted)">${esc(s.top)}</td></tr>`).join('');

function hl(text, q){
  const e = esc(text);
  if (!q) return e;
  return e.replace(new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&') + ')','ig'),
                   '<mark>$1</mark>');
}

function render(){
  const q = query.trim().toLowerCase();
  const list = D.themes
    .map(t => {
      const revs = q ? t.reviews.filter(r => r.t.toLowerCase().includes(q)) : t.reviews;
      return {...t, shown: revs};
    })
    .filter(t => !q || t.shown.length)
    .sort((a,b) => sortKey === 'n' ? b.n - a.n : b.votes - a.votes);

  const max = Math.max(1, ...list.map(t => sortKey === 'n' ? t.n : t.votes));
  const totalHits = list.reduce((s,t) => s + t.shown.length, 0);
  document.getElementById('hits').textContent =
    q ? `${fmt(totalHits)} review${totalHits===1?'':'s'} in ${list.length} theme${list.length===1?'':'s'}` : '';

  const box = document.getElementById('themes');
  if (!list.length){ box.innerHTML = '<p class="empty">No review contains that word.</p>'; return; }

  box.innerHTML = list.map((t,i) => {
    const cap = q ? t.shown : t.shown.slice(0,15);
    const bar = ((sortKey==='n'? t.n : t.votes)/max*100).toFixed(1);
    return `<section class="theme${q?' open':''}">
      <div class="thead" tabindex="0" role="button" aria-expanded="${q?'true':'false'}">
        <span class="rk">#${i+1}</span>
        <div>
          <h3 class="tname">${esc(t.name)}</h3>
          <div class="tmeta">
            <span><b>${fmt(t.n)}</b> reviews</span>
            <span>${fmt(t.votes)} helpful votes</span>
            <span>mean ${t.mean}★</span>
            <span>${t.from} → ${t.to}</span>
            <span class="rid">cluster ${t.clusters.join(', ')}</span>
          </div>
          <div class="track" style="margin-top:9px;max-width:380px"><i style="width:${bar}%"></i></div>
        </div>
        <span class="chev">${q ? fmt(t.shown.length)+' match' : 'open'}</span>
      </div>
      <div class="body">
        ${cap.map(r => `<div class="rev${r.u>=5?' up':''}">
          <div class="rmeta">
            <span class="stars">${'★'.repeat(r.s)}${'☆'.repeat(5-r.s)}</span>
            <span>${r.d}</span>
            ${r.u ? `<span class="votes">${fmt(r.u)} found helpful</span>` : ''}
            <span class="rid">${esc(r.id.slice(0,8))}</span>
          </div>${hl(r.t, query.trim())}</div>`).join('')}
        ${!q && t.shown.length>15 ? `<div class="more">+ ${fmt(t.shown.length-15)} more reviews in this theme</div>`:''}
      </div>
    </section>`;
  }).join('');

  box.querySelectorAll('.thead').forEach(h => {
    const toggle = () => {
      const s = h.parentElement; s.classList.toggle('open');
      h.setAttribute('aria-expanded', s.classList.contains('open'));
    };
    h.addEventListener('click', toggle);
    h.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); toggle(); }
    });
  });
}

document.getElementById('q').addEventListener('input', e => { query = e.target.value; render(); });
document.getElementById('byN').addEventListener('click', () => setSort('n'));
document.getElementById('byV').addEventListener('click', () => setSort('v'));
function setSort(k){
  sortKey = k === 'n' ? 'n' : 'votes';
  document.getElementById('byN').setAttribute('aria-pressed', k==='n');
  document.getElementById('byV').setAttribute('aria-pressed', k!=='n');
  render();
}
render();
</script>
</body></html>
"""

out = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
with open("dashboard.html", "w", encoding="utf-8") as f:
    f.write(out)

print(f"wrote dashboard.html")
print(f"  {len(data)} themes, {n_themed} reviews, {sum(d['votes'] for d in data)} helpful votes")
print(f"  funnel: {n_raw} collected -> {n_clean} with content -> {n_themed} in themes")
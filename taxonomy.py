"""
Loads themes_v2.json: internal cluster id (as stored in reviews.db) -> display id, theme, name.

Clusters not in the file (found in the bucket after it was written, or after a reset) are
not dropped: they go to the 'bucket_found' group, with display ids after the highest mapped
one, in internal-id order, and the name "Not yet named".
"""
import json
import config as C

UNMAPPED_THEME = "bucket_found"


def load(internal_ids=()):
    m = json.load(open(C.THEMES_V2_FILE, encoding="utf-8"))
    themes = {t["key"]: dict(t) for t in m["themes"]}
    clusters = {int(k): dict(v) for k, v in m["clusters"].items()}
    nxt = max(v["id"] for v in clusters.values()) + 1
    for c in sorted(set(internal_ids) - set(clusters)):
        clusters[c] = {"id": nxt, "theme": UNMAPPED_THEME, "name": "Not yet named", "unmapped": True}
        themes[UNMAPPED_THEME]["clusters"].append(nxt)
        nxt += 1
    return themes, clusters

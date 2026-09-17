import sqlite3, numpy as np, umap, hdbscan, collections
from sentence_transformers import SentenceTransformer

con = sqlite3.connect("reviews.db")
rows = con.execute("SELECT review_id, text FROM reviews_clean").fetchall()
ids = [r[0] for r in rows]; texts = [r[1] for r in rows]
target = {r[0] for r in con.execute("SELECT review_id FROM clusters WHERE cluster = 17")}
con.close()

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
emb = model.encode(texts, batch_size=64, show_progress_bar=True)
np.save("emb.npy", emb)          # saves it so future runs are instant

idx = [i for i, rid in enumerate(ids) if rid in target]
sub = emb[idx]
print(len(sub), "reviews in theme 2")

red = umap.UMAP(n_components=5, n_neighbors=15, min_dist=0.0,
                metric="cosine", random_state=42).fit_transform(sub)
lab = hdbscan.HDBSCAN(min_cluster_size=25, min_samples=5,
                      cluster_selection_method="leaf").fit_predict(red)

c = collections.Counter(lab)
print(f"noise {c[-1]}, sub-clusters {len([k for k in c if k != -1])}\n")
for cid, n in sorted([(k, v) for k, v in c.items() if k != -1], key=lambda x: -x[1]):
    print(f"--- sub {cid} ({n}) ---")
    for j in [idx[i] for i, l in enumerate(lab) if l == cid][:5]:
        print("   ", texts[j][:120])
    print()

con = sqlite3.connect("reviews.db")
for i, l in enumerate(lab):
    rid = ids[idx[i]]
    con.execute("UPDATE clusters SET cluster = ? WHERE review_id = ?",
                (100 + int(l) if l != -1 else -1, rid))
con.commit(); con.close()
print("saved sub-clusters as 100-106")
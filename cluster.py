import sqlite3, collections
from sentence_transformers import SentenceTransformer
import umap, hdbscan

con = sqlite3.connect("reviews.db")
rows  = con.execute("SELECT review_id, text FROM reviews_clean").fetchall()
ids   = [r[0] for r in rows]
texts = [r[1] for r in rows]
print(len(texts), "reviews")

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
emb = model.encode(texts, batch_size=64, show_progress_bar=True)
print("embeddings:", emb.shape)

red = umap.UMAP(n_components=5, n_neighbors=30, min_dist=0.0,
                metric="cosine", random_state=42).fit_transform(emb)

labels = hdbscan.HDBSCAN(min_cluster_size=40, min_samples=10,
                         metric="euclidean",
                         cluster_selection_method="leaf").fit_predict(red)

con.execute("DROP TABLE IF EXISTS clusters")
con.execute("CREATE TABLE clusters (review_id TEXT PRIMARY KEY, cluster INTEGER)")
con.executemany("INSERT INTO clusters VALUES (?,?)",
                list(zip(ids, [int(l) for l in labels])))
con.commit()

c = collections.Counter(labels)
print(f"\nnoise: {c[-1]} ({c[-1]/len(labels)*100:.0f}%)")
print(f"clusters: {len([k for k in c if k != -1])}\n")

for cid, n in sorted([(k,v) for k,v in c.items() if k != -1], key=lambda x: -x[1]):
    print(f"--- cluster {cid}   ({n} reviews) ---")
    for t in [texts[i] for i,l in enumerate(labels) if l == cid][:3]:
        print("   ", t[:110])
    print()

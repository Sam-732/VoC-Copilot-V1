import sqlite3, re, itertools, collections
import pandas as pd

df = pd.read_excel("reviews_labelled.xlsx")

def norm(s):
    if pd.isna(s): return None
    s = str(s).lower().strip()
    s = re.sub(r'\(.*?\)|\?', ' ', s)
    s = re.split(r'\+| or ', s)[0]                 # primary complaint only
    s = re.sub(r'\s+', ' ', s).strip()
    fix = {'cusomter care':'customer care','customer service':'customer care',
           'mising item':'missing item','no delivey':'no delivery',
           'poor packaging':'packaging','packaging issue':'packaging',
           'price issue':'price','cancellation price issue':'cancellation issue',
           'need more discount':'feature request','want more offer':'feature request'}
    return fix.get(s, s) or None

df['label'] = df['my_label'].map(norm)
gold = df[df['label'].notna() & (df['label'] != 'no_signal')][['review_id','label']].copy()

con = sqlite3.connect("reviews.db")
clus = dict(con.execute("SELECT review_id, cluster FROM clusters").fetchall())
clean_ids = {r[0] for r in con.execute("SELECT review_id FROM reviews_clean")}
con.close()

gold['in_clean'] = gold['review_id'].isin(clean_ids)
gold['cluster']  = gold['review_id'].map(clus)
scored = gold[gold['cluster'].notna() & (gold['cluster'] != -1)]

print(f"labelled complaints:   {len(gold)}")
print(f"  survived cleaning:   {gold['in_clean'].sum()}")
print(f"  got a cluster:       {len(scored)}")
print(f"  went to noise:       {(gold['cluster'] == -1).sum()}")
print(f"COVERAGE: {len(scored)/max(gold['in_clean'].sum(),1)*100:.0f}%\n")

pairs = list(itertools.combinations(scored.itertuples(), 2))
same_l = sum(1 for a,b in pairs if a.label == b.label)
same_c = sum(1 for a,b in pairs if a.cluster == b.cluster)
both   = sum(1 for a,b in pairs if a.label == b.label and a.cluster == b.cluster)
print(f"pairs: {len(pairs)}")
print(f"PRECISION: {both/same_c*100:.0f}%   (machine grouped -> you agreed)")
print(f"RECALL:    {both/same_l*100:.0f}%   (you grouped -> machine agreed)\n")

print("--- where each of your categories ended up ---")
by_l = collections.defaultdict(list)
for r in gold.itertuples():
    by_l[r.label].append(r.cluster)
for lab, cs in sorted(by_l.items(), key=lambda x: -len(x[1])):
    real = [c for c in cs if pd.notna(c) and c != -1]
    print(f"  {lab:20} n={len(cs):3}  clustered={len(real):3}  across {len(set(real))} clusters")
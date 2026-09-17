from google_play_scraper import reviews, Sort

batch, token = reviews(
    "in.swiggy.android",
    lang="en",
    country="in",
    sort=Sort.NEWEST,
    count=200,
)

print("got:", len(batch))
print("newest:", batch[0]["at"])
print("oldest:", batch[-1]["at"])
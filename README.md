# Mundo Compacto: data

The open pipeline behind **Mundo Compacto**, a wall of the words most present in Brazilian news.
Every hour it reads public RSS feeds and publishes
[`data/latest.json`](https://josedihego.github.io/mundo-compacto-data/data/latest.json).
It runs fully automatically, with no human editing.
It's non-commercial: no ads and no money involved.

## Method

1. **Fetch** the feeds in [config/feeds.json](config/feeds.json). Only headline, outlet, link and time are kept,
   for 7 days. Article text, summaries and images are never stored.
2. **Extract** terms from each headline with spaCy's Portuguese model (`pt_core_news_sm`):
   - people, places and organisations;
   - topics: a noun plus the adjectives after it, kept as **one** expression.
     `"O governo Brasileiro decide cortar impostos"` → `governo brasileiro`, `imposto`.
   - Verbs, articles and the public [stopwords](config/stopwords.txt) never count.
   - Matching ignores accents, case and plurals. [aliases.json](config/aliases.json) merges name variants
     (`presidente Lula` → `Lula`) and fixes categories.
3. **Score**: the number of **different outlets** mentioning the term in the window (6 h, 24 h, 7 days),
   not the number of articles. Top 60 per window.
4. **Trend**: the score in the previous window of the same length. For 7 days this comes from a snapshot
   of per-term counts, because headlines are kept for only 7 days.
5. **Crime flag**: a term is flagged if any of its words is in [crime_terms.txt](config/crime_terms.txt),
   for an optional filter in the app.
6. **Feed health**: a feed failing 3 runs in a row opens an issue, which closes itself when the feed recovers.

## Output

`data/latest.json` on the `gh-pages` branch, served by GitHub Pages:

```jsonc
{
  "generated_at": 1794413460,
  "windows": {
    "6h":  {"span_hours": 6,  "terms": [ /* top 60 */ ]},
    "24h": {"span_hours": 24, "terms": [...]},
    "7d":  {"span_hours": 168, "terms": [...]}
  },
  // term: {"key","label","category": person|place|organisation|topic,"crime",
  //        "score": distinct outlets,"articles","prev","trend","refs": [headline ids]}
  "headlines": {"<id>": {"o": "outlet id", "t": "headline", "u": "link", "ts": 1794413460}},
  "outlets": {"g1": {"name": "g1", "ok": true}}
}
```

The public lists are also published, under `lists/`.

## Copyright

Only the headline, the outlet's name, the time and a link to the original article are published.
Headlines and trademarks belong to their outlets. An outlet that prefers not to be included can open an
issue, and its feed will be removed.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pipeline.build                       # -> data/latest.json
.venv/bin/python -m unittest discover -s tests -t .
```

To run it on your own server instead of Actions: `scripts/run_hourly.sh /var/www/site` from cron (`17 * * * *`).

## Reliable hourly runs

GitHub's own `schedule` trigger can be delayed or skipped, so the workflow has none. A server starts it every hour
with [scripts/server_trigger.sh](scripts/server_trigger.sh) from cron (`17 * * * *`). It uses a fine-grained token
limited to this repository with "Actions: read and write". The workflow can also be started by hand from the Actions tab.

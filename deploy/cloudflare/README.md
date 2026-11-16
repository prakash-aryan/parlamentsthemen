# Public read-only version on Cloudflare

This folder holds the version that runs at https://parlamentsthemen.prakasharyan.dev. It serves the stored results without a GPU and without a model at request time, so the "Warum" explanations, topic reports, review mode and live classification are switched off. Search, topic browsing, the overview, affair details and similar affairs work as in the full service.

| Part | What it does |
|---|---|
| `worker/` | Cloudflare Worker: serves the static search page (`web/out`) and the read-only API under `/api` |
| `embedder/` | Container with the query encoder (harrier-oss-v1-0.6b on CPU) that turns a search query into a vector |
| D1 | Affairs, their texts (first 1,800 characters), English titles and the "yes" topic decisions |
| Zilliz Cloud | The 1,024-dimensional search vectors of all affairs, with level, parliament, year and topics as filter fields |
| `scripts/` | Export from PostgreSQL, import into D1, vector upload and the English title translation |

## Build it

1. Build the page in static mode: `cd web && NEXT_PUBLIC_API_BASE=/api NEXT_PUBLIC_STATIC=1 npm run build`.
2. Put the encoder into the container folder: `huggingface-cli download microsoft/harrier-oss-v1-0.6b --local-dir deploy/cloudflare/embedder/model`.
3. Create a D1 database and a Zilliz Cloud cluster, then replace the placeholders in `worker/wrangler.jsonc` with the D1 database id, the cluster endpoint and your hostname.
4. Export and import the data: `uv run python deploy/cloudflare/scripts/export_d1.py` writes SQL files to `runs/d1`; `deploy/cloudflare/scripts/import_d1.sh runs/d1` loads them and can be restarted. `ZILLIZ_URL=... ZILLIZ_TOKEN=... uv run python deploy/cloudflare/scripts/upload_vectors.py` uploads the vectors.
5. Deploy: `cd deploy/cloudflare/worker && npm install && npx wrangler secret put ZILLIZ_TOKEN && npx wrangler deploy`.

`src/data/*.json` are snapshots of `GET /topics` and `GET /bodies` from the full service and the legacy topic map; refresh them when cards change.

## English titles

Affair titles are translated into English once with Apertus 1.5 8B (text-only checkpoint, vLLM, greedy decoding) and shown when the interface is set to English; the original title stays available. `scripts/titles_en.py export` writes the titles, `scripts/translate_titles.py` translates one shard on a GPU (`translate_titles.sbatch` runs it under Slurm). `scripts/titles_en.py to_d1` drops outputs that repeat the instruction, are cut off or belong to number-only titles, then writes the D1 updates. 322,305 of 323,441 titles have an English version; the rest keep the original. `scripts/translate_names.py` translated the missing Romansh topic names and outcome words and the German-only St. Gallen topics in the same way; the results are in `cards/topic_names.json`, with two terms corrected by hand.

## Limits and costs

- One encoder container at most; it sleeps after 10 idle minutes, so the first search after a pause waits about 20 seconds. The page starts it when it loads.
- Query vectors are cached in D1. Search responses are cached for 10 minutes at the edge.
- Each address may send 240 API requests and start 40 new query encodings per minute. The whole site starts at most 3,000 new encodings per day.
- A spending cap on the Cloudflare account stops Workers and Durable Objects at a fixed monthly amount.
- Search counts (endpoint, query text, filters, response time, country) go to Workers Analytics Engine without IP addresses or cookies.

## Quality

An automated relevance check, with a separate language model as the judge, rated the results the public site returned for 73 search queries and 25 topic lists (ten results each, 0 to 2 per result). Clearly relevant: 75% for queries in the national languages, 76% for English queries and 94% for topic lists; 84% to 96% of the top three results were clearly relevant. Romansh queries are the weak point of the query encoder: some return unrelated affairs. When even the best match of a plain search is weak (cosine similarity below 0.645), the page says so above the results. Two rounds of eight browser sessions used the page as different visitors. The four bugs they found are fixed, and the weak-match note and the translated topic names came out of their findings. Open points: one topic list mixes several schemes with similar names (grouped in the menu), the detail text stays in its original language, and status words from some parliaments stay German.

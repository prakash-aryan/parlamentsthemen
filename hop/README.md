# Nightly update with Apache Hop

The nightly job keeps the topic table current. It asks the OpenParlData API for every affair updated since a given date (sorted by `updated_at`), builds one cleaned text per affair in exactly the way the initial data preparation does, and compares its hash and the hash of every active topic card with what PostgreSQL already holds. Only affairs whose text changed, whose topic answers are missing or come from an older card, or whose answers come from an older model revision are classified again. The results are written to `affairs` and `affair_topics`, the scored text to `affair_texts` (so the page shows the text the decision was made on), and new texts also get an embedding in `affair_embeddings`.

## What is in this folder

| File | Purpose |
|---|---|
| `nightly.hwf` | Apache Hop workflow: Start, then a Shell action that runs the job, then Success or Abort depending on its exit code |
| `run_nightly.sh` | The command the Shell action runs; it can also be called directly from cron |
| `project-config.json`, `metadata/` | The Hop project and its local run configurations |
| `Dockerfile` | An image with Apache Hop 2.19.0, Java 21 and the Python package with its locked dependencies |

The job itself is `python -m parltopics.nightly --since YYYY-MM-DD [--limit N] [--topics a,b] [--dry-run] [--no-embed]`.

## Running it

From cron, on a host with the project installed (`uv sync --extra db --extra embed`):

```
15 4 * * * cd /path/to/repository && hop/run_nightly.sh >> runs/nightly.log 2>&1
```

With Apache Hop in Docker, from the repository root:

```
docker build -f hop/Dockerfile -t parltopics-hop:2.19.0 .
docker run --rm --network host -e DATABASE_URL=... -e LLM_BASE_URL=... -e LLM_NAME=... -e LLM_API_KEY=... \
  parltopics-hop:2.19.0 --parameters=SINCE=2026-10-18
```

Without `SINCE`, the job processes the affairs updated since yesterday. The container exits with 0 when the workflow ends in Success and with 1 when it ends in Abort, so a scheduler can alert on it.

## Configuration

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | PostgreSQL with the tables created by `python -m parltopics.db init` (required) |
| `PARLTOPICS_DECISION_URL` | Base URL of the trained decision model's server; when set, all topic questions of an affair are answered in one request and the stored Apertus-ParlTopics-8B calibrations are used |
| `LLM_BASE_URL`, `LLM_NAME`, `LLM_API_KEY` | An OpenAI-compatible Apertus endpoint with token log-probabilities; used when `PARLTOPICS_DECISION_URL` is not set (one yes/no readout per topic) |
| `PARLTOPICS_AUTH_HEADER` | Alternative to `LLM_API_KEY`: a file containing one HTTP header line |
| `NIGHTLY_ARGS` | Extra options for the job, for example `--limit 50 --no-embed` |

Each stored row records which path produced it in `model_revision` and whether a fitted calibration was available in `calibrated`. The trained model's server is the intended production path; the yes/no readout is the fallback for hosts without a GPU.

## Measured test runs (19 October 2026)

| Run | Result |
|---|---|
| Text check against the initial preparation, 12 affairs (federal texts, cantonal and city documents, title only) | Identical hash for all 12 |
| Job, last 3 days, 20 affairs, Apertus 8B yes/no readout on the hosted endpoint | 20 fetched, 6 unchanged, 14 classified (405 topic rows), 1 new embedding, 0 failures, 79.7 s |
| Same job again | 20 unchanged, nothing classified, 2.1 s |
| Hop workflow in Docker, 20 affairs | Start, job, Success; 20 unchanged; workflow 5.5 s |
| Hop workflow in Docker, 25 affairs | 24 unchanged, 1 classified (29 rows), Success; workflow 7.0 s |
| Hop workflow in Docker, database unreachable | Job fails, workflow takes the Abort branch, container exit code 1 |

The OpenParlData API updates the `updated_at` field of many affairs during its own nightly harvest, so the list of updated affairs is longer than the list of affairs whose content changed; the hash check keeps the classification work to the changed ones.

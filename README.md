# Parlamentsthemen: topic classification for Swiss parliamentary affairs with Apertus

OpenParlData.ch collects more than 300,000 affairs from Swiss federal, cantonal and municipal parliaments in four languages, but they are primarily searchable by full text, and the few topic labels that exist follow different schemes. Parlamentsthemen is an open, reusable classification service based on Apertus: it assigns the two-level standard scheme of Année Politique Suisse (APS), parliaments' own schemes and ad-hoc topics defined by users without retraining, and it is applied to a concrete use case of Digital Public Services Switzerland: finding digitalisation affairs across the whole dataset.

| Models | URL |
|---|---|
| Apertus v1.5 8B (base) | [huggingface.co/swiss-ai/Apertus-v1.5-8B](https://huggingface.co/swiss-ai/Apertus-v1.5-8B) |
| Apertus v1.5 70B (drafting topic cards) | [huggingface.co/swiss-ai/Apertus-v1.5-70B](https://huggingface.co/swiss-ai/Apertus-v1.5-70B) |
| Apertus-ParlTopics-8B (our trained decision model) | [huggingface.co/merabro/Apertus-ParlTopics-8B](https://huggingface.co/merabro/Apertus-ParlTopics-8B) |

## How it works

![How the service works](figures/fig_system.png)

Every topic of every scheme is written as a short **topic card**. Apertus 1.5 8B, trained as a **decision model** (Apertus-ParlTopics-8B), reads an affair once and returns one score per card in a single pass; scores are calibrated where labelled earlier affairs exist. APS chapters, a canton's categories and an ad-hoc topic such as digitalisation are sets of cards that operators add, so a new topic needs no retraining (its threshold still needs validation). Stored results come from Apertus-ParlTopics-8B: all 29 topics for the 49,978 affairs from 2024 to 2026, and digitalisation for all 318,801 affairs; the other 28 topics for the older affairs are being added. Live decisions for affairs without stored results come from Apertus-ParlTopics-8B when its server is configured (`PARLTOPICS_DECISION_URL`), otherwise from untrained Apertus 1.5 8B; the "Warum" explanations use untrained Apertus 1.5 8B through the `LLM_*` endpoint. Anyone can report a wrong topic; reports are stored for review. Results are stored in PostgreSQL with pgvector, served by FastAPI, and shown on a search page in German, French, Italian and Romansh (interface languages) that can read results aloud and accept a spoken query.

- Technical report: [technical_report.md](technical_report.md) and `Invincibles_Report.pdf`
- Demo video: to be added
- Trained model, configuration, metrics and model card: https://huggingface.co/merabro/Apertus-ParlTopics-8B

## The structure

| Path | What it is |
| --- | --- |
| `README.md` | Overview, setup and usage |
| `technical_report.md` | The deeper write-up: architecture, evaluation, limitations |
| `LICENSE` | Apache-2.0 |
| `src/` | Our code: the Python package `src/parltopics` (data preparation, topic cards, decision model client, evaluation, database, API) |
| `web/` | The search page (Next.js, TypeScript), exported as static files and served by the API |
| `cards/` | Topic cards (YAML) and their names in five languages |
| `models/` | Calibration and thresholds per topic |
| `scripts/gpu/` | Kev setup, training and the model server |
| `third_party/kev/` | The patch that adapts Kev to Apertus 1.5 |
| `figures/` | Figures used in this README and in the technical report |

## Environment

The service reads these variables (copy `.env.example` to `.env`):

```
LLM_NAME: name and version of the model
LLM_BASE_URL: endpoint base URL
LLM_API_KEY: your API key
```

`LLM_*` point to an OpenAI-compatible Apertus endpoint that returns token log-probabilities (a hosted Apertus or a local vLLM server); it is used for quoting passages and, when `PARLTOPICS_DECISION_URL` is not set, for live classification of affairs that are not yet stored. Set `PARLTOPICS_DECISION_URL` to a Apertus-ParlTopics-8B server (Kev's server with the adapter, `scripts/gpu/serve_model.sh`) so that live decisions come from the trained model. `DATABASE_URL` and `POSTGRES_PASSWORD` configure PostgreSQL.

Topics are suggestions that people can correct. Set `PARLTOPICS_REVIEW_TOKEN` to an access code to enable review mode: reviewers sign in on the page ("Prüfmodus" in the footer), work through reported topics, confirm or remove any topic of an affair and add missed ones. Each correction is stored with the reviewer's name next to the model's original decision. Without the code, review mode is off and visitors can only report a topic.

Read-aloud and voice search are optional. With `ELEVENLABS_API_KEY` set, the server converts text to speech with ElevenLabs (`eleven_v4_turbo`, voice `ELEVENLABS_VOICE_ID`) and transcribes spoken search queries (`scribe_v2`); the key stays on the server, generated audio is cached in `runs/speech`, and `PARLTOPICS_SPEECH_DAILY_CHARS` caps the characters sent per day (default 20,000). Without the key the page falls back to the browser's built-in speech and hides voice search. ElevenLabs is an external service: the text being read and, for voice search, the recorded query leave the deployment, so an operator who requires a fully on-premise service leaves the key unset.

## Run it

Requirements: Docker with Compose, about 5 GB of free disk space and 2 GB of RAM. No GPU is needed. Compose starts two services: PostgreSQL with pgvector, and the container that serves the page and the API.

The repository includes a demo bundle in `data/demo/` so that a fresh clone runs without the prepared corpus. It holds 5,000 real affairs from 88 parliaments at all four levels, in German, French and Italian, 85% of them from 2024 to 2026, together with their texts, their search embeddings and the 123,385 topic decisions that Apertus-ParlTopics-8B stored for them. `data/demo/manifest.json` lists the counts.

```bash
cp .env.example .env    # set POSTGRES_PASSWORD; everything else is optional
docker compose up -d db
docker compose build app
docker compose run --rm app python -m parltopics.demo load --dir data/demo
docker compose up -d app
curl -s localhost:8765/health    # wait for "encoder": "ready", then open http://localhost:8765
```

We ran these commands on a fresh copy of the repository. Building the image took 5.4 minutes with the base images already pulled, and loading the bundle took 14 seconds. On its first start the app downloads the query encoder (microsoft/harrier-oss-v1-0.6b, 1.1 GB) into the `hfcache` volume. Until the encoder is loaded, `/health` reports `"encoder": "loading"` and searches wait; on our connection this took 6.7 minutes. Later starts are ready after about 20 seconds. If port 8765 or 5433 is already in use, set `APP_PORT` or `DB_PORT` in `.env`.

Without an Apertus endpoint, everything that reads stored results works: search in any language with spelling suggestions, the topic filter and topic browsing for the 30 topics with stored decisions, the overview by outcome, affair details, similar affairs and reports of wrong topics. Two features need a model at request time: live classification of topics that have no stored decisions (`POST /classify`), and the "Warum" explanations with the quoted passage. Without an endpoint these calls return HTTP 503 with a message that names the missing setting, and `/topics` lists only the topics with stored decisions. To enable them, set `LLM_BASE_URL`, `LLM_NAME` and `LLM_API_KEY` in `.env` to an OpenAI-compatible Apertus endpoint that returns token log-probabilities, then run `docker compose up -d app` again.

Live decisions then come from untrained Apertus. To take them from the trained model, start an Apertus-ParlTopics-8B server (`scripts/gpu/serve_model.sh` starts Kev's server with the adapter on one GPU, port 8350) and set `PARLTOPICS_DECISION_URL` to its address. Inside the container, a server on the Docker host is `http://host.docker.internal:8350`. It must listen on an address the container can reach, such as the Docker bridge, and not only on 127.0.0.1; an SSH tunnel to the GPU server can bind there with `ssh -N -L 172.17.0.1:8350:localhost:8350 <gpu-server>`. The explanations still use `LLM_BASE_URL`.

The demo covers 5,000 of the 318,801 affairs, so counts and result lists are smaller than in the full service. To run on the full corpus, prepare `data/` and `runs/` as described in "Reproduce the results" and load them in place of the bundle:

```bash
for step in init affairs embeddings index topics export; do
  docker compose run --rm app python -m parltopics.db $step
done
docker compose run --rm app python -m parltopics.db scores --dir <score folders> --run-id parltopics8b_corpus
```

Local development without Docker: `uv sync --extra db --extra embed`, `cd web && npm ci && npm run build`, then `uv run uvicorn parltopics.api:app --port 8765`. `docker compose up -d db` exposes PostgreSQL on `127.0.0.1:5433` (or `DB_PORT`), which is where the `DATABASE_URL` in `.env.example` points.

### API

| Endpoint | Returns |
|---|---|
| `GET /search?q=&topic=&level=&body=&year_from=&year_to=` | Affairs ranked by meaning (any language), filtered by topic, level, parliament and years |
| `GET /overview` (same filters) | Counts by parliament and status category (adopted, rejected, pending, and so on), inferred from each affair's status text; for a text query, over the 100 best matches |
| `GET /topics` | All topic cards with names in five languages and their scope |
| `GET /affairs/{id}/detail`, `/similar`, `/topics`, `/topics/live` | One affair: details and links, similar affairs, stored and live topics |
| `GET /topics/{topic}/affairs?decision=&min_probability=&order=&since=&until=` | Stored affairs for a topic, with `corrected` and `original_decision` where a reviewer changed the decision; for example the weekly digitalisation shortlist for DVS: `/topics/adhoc_digitalisation/affairs?min_probability=0.02735447&order=newest&since=2026-10-12` (the monitoring threshold from `models/monitoring_adhoc_digitalisation_parltopics8b.json`: recall 0.97 at precision 0.18 on the test affairs) |
| `POST /classify` | A live decision for any affair from the OpenParlData API (Apertus-ParlTopics-8B when `PARLTOPICS_DECISION_URL` is set, otherwise untrained Apertus via `LLM_*`), with probability, passage and reason |
| `POST /flags`, `GET /flags` | Report a topic that looks wrong (stored for review); list reports. Reviewers record corrections with `python -m parltopics.corrections add|list|from-flags` |
| `GET /review`, `GET /review/queue`, `POST /review/corrections` | Whether review mode is configured; open reports; a reviewer's correction (`affair_id`, `topic`, `decision`, `reviewer`, optional `reason`), with the header `X-Review-Token` set to `PARLTOPICS_REVIEW_TOKEN`. The model's original decision is kept |
| `GET /speech`, `POST /speech`, `POST /speech/transcribe` | Whether read-aloud and voice search are available; speech for a text in de, fr, it, rm or en (MP3); the text and language of a recorded query |

## Nightly update and Apache Hop

`uv run python -m parltopics.nightly --since YYYY-MM-DD` fetches affairs created or changed since the date from the OpenParlData API, skips those whose text hash is unchanged, scores the rest for every active topic card and writes the rows to PostgreSQL. `hop/nightly.hwf` is an Apache Hop workflow that runs the job after OpenParlData's nightly export and branches on success or failure; `hop/README.md` shows how to run it with the Hop image (`hop/Dockerfile`) or from cron (`hop/run_nightly.sh`). Set `PARLTOPICS_DECISION_URL` to the trained model's server for production; without it the job uses the `LLM_*` endpoint. Tested manually with the `LLM_*` path; scheduling and the trained-model path remain to be validated.

## Reproduce the results

1. **Data.** Put the OpenParlData export (`https://files.openparldata.ch/exports/`) and the label folder (`https://files.openparldata.ch/hackapertus/`) in this layout, then run `uv run python -m parltopics.prepare --raw data/raw --out data` and `uv run python -m parltopics.labels --raw data/raw --data data`:

   ```
   data/raw/export/affairs.ndjson.gz
   data/raw/export/bodies.ndjson.gz
   data/raw/export/docs/docs_*.ndjson.gz
   data/raw/labels/   (all label folder files, including che_affair_texts.ndjson.gz)
   ```

2. **Topic cards.** `uv run python -m parltopics.cards` drafts a topic card with Apertus 70B; the cards used in this work are in `cards/`.
3. **Training.** `scripts/gpu/kev_setup.sh` installs Kev at upstream commit 1f04cfa with `third_party/kev/apertus.patch`; `parltopics.build_train` and `parltopics.build_extra` write the training data; `scripts/gpu/launch_train.sh` trains. Apertus-ParlTopics-8B's configuration, metrics, adapter (159 MB) and head (8 MB) are on https://huggingface.co/merabro/Apertus-ParlTopics-8B.
4. **Corpus labelling.** `scripts/gpu/serve_model.sh` serves the trained model; `parltopics.systemone_multi` scores affairs against it for a set of topic cards, and `parltopics.db scores` loads the results. `parltopics.embed` computes the search embeddings.
5. **Results.** The technical report describes the evaluation sets, the baselines and the metrics; `parltopics.evaluate` holds the calibration and metric functions.

The GPU scripts read the data folder on the GPU server from `DATA_ROOT`. Hardware used: four RTX A6000 (48 GB).

## Credits

- AI tools were used for documentation and debugging.
- The decision-model training and serving code is adapted from Kev (github.com/jaredpalmer/kev, Apache-2.0), an open implementation of the idea behind TypeSafe's System One models.
- Data: OpenParlData.ch (open government data); Curia Vista data from the Parliamentary Services of the Federal Assembly.
- Models: Apertus 1.5 by the Swiss AI Initiative (Apache-2.0, gated download with an acceptable use policy); harrier-oss-v1-0.6b (MIT).
- Compute: CSCS inference via the Keera gateway; our own GPU server (four RTX A6000).

## License

Code under Apache-2.0 (see `LICENSE`). OpenParlData.ch data under CC BY 4.0 (source: OpenParlData.ch). Apertus 1.5 under Apache-2.0 with an acceptable use policy.

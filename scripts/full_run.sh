R=/nvmedata/prakasharyan/liebefeld
gpu=$1; port=$2; run=${3:-G_desc}; cards=${4:-cards/digitalisation_v2.yaml}
out=${5:-$R/runs/full}
cd $R/ext/kev
CUDA_VISIBLE_DEVICES=$gpu HF_HUB_OFFLINE=1 KEV_TRUNCATE_STATES=1 $R/ext/kev-venv/bin/python -m kev.serve --run $R/kev_runs/$run --port $port > ~/liebefeld/logs/serve_full_$gpu.log 2>&1 &
spid=$!
for i in $(seq 1 120); do curl -s -m 3 -o /dev/null http://127.0.0.1:$port/v1/models && break; kill -0 $spid 2>/dev/null || { echo "SERVER_DIED gpu $gpu"; tail -20 ~/liebefeld/logs/serve_full_$gpu.log; exit 1; }; sleep 5; done
echo "SERVER_READY gpu $gpu"
cd ~/liebefeld/code
py="env UV_PROJECT_ENVIRONMENT=$R/venv /home/prakasharyan/.local/bin/uv run python"
for f in $out/chunks/chunk_*.parquet; do
  n=$(basename $f .parquet)
  mkdir $out/claims/$n 2>/dev/null || continue
  t0=$(date +%s)
  $py -m parltopics.systemone_multi --input $f --cards $cards --base-url http://127.0.0.1:$port --out-dir $out/scores --prefix $n --split full --compact --concurrency 16 | tail -1
  echo "$(date +%H:%M) $n gpu $gpu $(( $(date +%s) - t0 )) s" >> $out/timing.txt
done
kill $spid
echo "FULL_WORKER_DONE gpu $gpu"

R=/nvmedata/prakasharyan/liebefeld
gpu=$1; run=$2; port=$3; compact=${4:---compact}
out=$R/runs/trained/$run; mkdir -p $out
cd $R/ext/kev
CUDA_VISIBLE_DEVICES=$gpu HF_HUB_OFFLINE=1 $R/ext/kev-venv/bin/python -m kev.serve --run $R/kev_runs/$run --port $port > ~/liebefeld/logs/serve_$run.log 2>&1 &
spid=$!
for i in $(seq 1 120); do curl -s -m 3 -o /dev/null http://127.0.0.1:$port/v1/models && break; kill -0 $spid 2>/dev/null || { echo "SERVER_DIED $run"; tail -20 ~/liebefeld/logs/serve_$run.log; exit 1; }; sleep 5; done
echo "SERVER_READY $run"
cd ~/liebefeld/code
py="env UV_PROJECT_ENVIRONMENT=$R/venv /home/prakasharyan/.local/bin/uv run python"
for s in dev test; do
  $py -m parltopics.systemone_multi --input $R/data/${s}_sample.parquet --cards cards/digitalisation_v2.yaml --base-url http://127.0.0.1:$port --out-dir $out --prefix $run --split $s $compact --concurrency 8
  $py -m parltopics.systemone_multi --input $R/data/curia_${s}_sample.parquet --cards cards/curia/*.yaml --base-url http://127.0.0.1:$port --out-dir $out --prefix $run --split $s $compact --concurrency 4
done
kill $spid
echo "EVAL_DONE $run"

R=/nvmedata/prakasharyan/liebefeld
gpu=${1:-1}; port=${2:-8350}
cd $R/ext/kev
CUDA_VISIBLE_DEVICES=$gpu HF_HUB_OFFLINE=1 KEV_TRUNCATE_STATES=1 nohup $R/ext/kev-venv/bin/python -m kev.serve --run $R/kev_runs/G_desc --port $port > ~/liebefeld/logs/serve_model_live.log 2>&1 < /dev/null &
echo $! > ~/liebefeld/logs/serve_model_live.pid
for i in $(seq 1 120); do curl -s -m 3 -o /dev/null http://127.0.0.1:$port/v1/models && { echo "SERVER_READY port $port pid $(cat ~/liebefeld/logs/serve_model_live.pid)"; exit 0; }; sleep 5; done
echo SERVER_TIMEOUT; exit 1

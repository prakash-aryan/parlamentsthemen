R=${DATA_ROOT:?set DATA_ROOT to the data folder on the GPU server}
gpu=${1:-0}; port=${2:-8350}; run=${3:-$R/kev_runs/apertus-parltopics-8b}
mkdir -p $R/logs
cd $R/ext/kev
CUDA_VISIBLE_DEVICES=$gpu HF_HUB_OFFLINE=1 KEV_TRUNCATE_STATES=1 nohup $R/ext/kev-venv/bin/python -m kev.serve --run $run --port $port > $R/logs/serve_model.log 2>&1 < /dev/null &
echo $! > $R/logs/serve_model.pid
for i in $(seq 1 120); do curl -s -m 3 -o /dev/null http://127.0.0.1:$port/v1/models && { echo "SERVER_READY port $port pid $(cat $R/logs/serve_model.pid)"; exit 0; }; sleep 5; done
echo SERVER_TIMEOUT; exit 1

cd ~/liebefeld/code
export UV_PROJECT_ENVIRONMENT=/nvmedata/prakasharyan/liebefeld/venv HF_HUB_CACHE=/nvmedata/prakasharyan/hf-cache HF_HUB_OFFLINE=1 CUDA_VISIBLE_DEVICES=1
~/.local/bin/uv run --extra embed python -m parltopics.xlmr --task curia --data /nvmedata/prakasharyan/liebefeld/data --out /nvmedata/prakasharyan/liebefeld/runs/xlmr --epochs 3 --n-train 20000 > ~/liebefeld/logs/xlmr_curia.log 2>&1 &
~/.local/bin/uv run --extra embed python -m parltopics.xlmr --task digit --data /nvmedata/prakasharyan/liebefeld/data --out /nvmedata/prakasharyan/liebefeld/runs/xlmr --epochs 3 > ~/liebefeld/logs/xlmr_digit.log 2>&1 &
wait
echo XLMR_ALL_DONE

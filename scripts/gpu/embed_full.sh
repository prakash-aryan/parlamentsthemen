R=/nvmedata/prakasharyan/liebefeld
cd ~/liebefeld/code
export UV_PROJECT_ENVIRONMENT=$R/venv HF_HUB_CACHE=/nvmedata/prakasharyan/hf-cache HF_HUB_OFFLINE=1
M=microsoft/harrier-oss-v1-0.6b
CUDA_VISIBLE_DEVICES=1 ~/.local/bin/uv run --extra embed python -m parltopics.embed --data $R/data --model $M --batch-size 64 --shard 0 --shards 2 --out $R/data/emb > ~/liebefeld/logs/embed_full_0.log 2>&1 &
p0=$!
CUDA_VISIBLE_DEVICES=3 ~/.local/bin/uv run --extra embed python -m parltopics.embed --data $R/data --model $M --batch-size 64 --shard 1 --shards 2 --out $R/data/emb > ~/liebefeld/logs/embed_full_1.log 2>&1 &
p1=$!
wait $p0; e0=$?; wait $p1; e1=$?
echo "shards exit $e0 $e1"
[ $e0 -eq 0 ] && [ $e1 -eq 0 ] && ~/.local/bin/uv run python -m parltopics.embed --data $R/data --model $M --shards 2 --out $R/data/emb --merge
echo EMBED_FULL_DONE

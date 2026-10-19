R=/nvmedata/prakasharyan/liebefeld
cd $R/ext/kev
[ -f $R/train/train_A.jsonl ] || head -n 5000 $R/train/train_compact_main.jsonl > $R/train/train_A.jsonl
gpu=$1; name=$2; data=$3; smooth=$4; ckpt=$5; batch=$6; accum=$7
CUDA_VISIBLE_DEVICES=$gpu HF_HUB_OFFLINE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True nohup $R/ext/kev-venv/bin/python -m kev.train \
  --base $R/models/apertus-1.5-8b-text --lora 16 --lr 5e-5 --dtype bf16 --weights_dtype bf16 --max_state ${MAXSTATE:-4096} --epochs ${EPOCHS:-1} --device cuda \
  --accum $accum --batch $batch --checkpointing $ckpt --length_sort 1 --data $R/train/$data --label_smoothing $smooth \
  --out $R/kev_runs/$name > ~/liebefeld/logs/train_$name.log 2>&1 < /dev/null &
echo "$name started on GPU $gpu, pid $!"

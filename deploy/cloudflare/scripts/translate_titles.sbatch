#!/bin/bash
#SBATCH --job-name=titles-en
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --nodes=1
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --requeue
#SBATCH --output=logs/titles_en_%A_%a.out
VLLM_USE_FLASHINFER_SAMPLER=0 HF_HUB_OFFLINE=1 exec python translate_titles.py ${SLURM_ARRAY_TASK_ID:-0} ${NSHARDS:-1} $LIMIT

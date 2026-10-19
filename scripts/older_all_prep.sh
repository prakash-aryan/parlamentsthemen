R=/nvmedata/prakasharyan/liebefeld
out=$R/runs/full_older_all; mkdir -p $out/chunks $out/claims $out/scores
cd ~/liebefeld/code
env UV_PROJECT_ENVIRONMENT=$R/venv /home/prakasharyan/.local/bin/uv run python -c "
import duckdb
t = duckdb.sql(\"select affair_id, text from read_parquet('$R/data/affair_text.parquet') where text is not null and length(trim(text)) > 0 and coalesce(year, 0) < 2024 order by coalesce(year, 0) desc, hash(affair_id)\").df()
size = 2500
for k, i in enumerate(range(0, len(t), size)):
    t.iloc[i:i + size].to_parquet(f'$out/chunks/chunk_{k:03d}.parquet', index=False)
print(len(t), 'older affairs, newest first, in', k + 1, 'chunks')
"

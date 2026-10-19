R=/nvmedata/prakasharyan/liebefeld
out=$R/runs/full2; mkdir -p $out/chunks $out/claims $out/scores
cd ~/liebefeld/code
env UV_PROJECT_ENVIRONMENT=$R/venv /home/prakasharyan/.local/bin/uv run python -c "
import duckdb
t = duckdb.sql(\"select affair_id, text, coalesce(year, 0) >= 2024 as recent from read_parquet('$R/data/affair_text.parquet') where text is not null and length(trim(text)) > 0 order by hash(affair_id)\").df()
recent, older = t[t.recent], t[~t.recent]
k = 0
for part, n in ((recent, 10), (older, 54)):
    for i in range(n):
        part.iloc[i::n][['affair_id', 'text']].to_parquet(f'$out/chunks/chunk_{k:02d}.parquet', index=False)
        k += 1
print(len(recent), 'recent affairs in 10 chunks,', len(older), 'older affairs in 54 chunks')
"

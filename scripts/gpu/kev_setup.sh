cd /nvmedata/prakasharyan/liebefeld/ext/kev
export UV_CACHE_DIR=/nvmedata/prakasharyan/uv-cache UV_PROJECT_ENVIRONMENT=/nvmedata/prakasharyan/liebefeld/ext/kev-venv
~/.local/bin/uv sync --extra serve 2>&1 | tail -5
echo KEV_SETUP_DONE

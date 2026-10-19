R=${DATA_ROOT:?set DATA_ROOT to the data folder on the GPU server}
cd $R/ext/kev
UV_PROJECT_ENVIRONMENT=$R/ext/kev-venv uv sync --extra serve 2>&1 | tail -5
echo KEV_SETUP_DONE

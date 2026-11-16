FROM python:3.12-slim
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir sentence-transformers
COPY model /model
COPY server.py /server.py
ENV HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
EXPOSE 8080
CMD ["python", "/server.py"]

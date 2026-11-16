import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from sentence_transformers import SentenceTransformer

PROMPT = "Instruct: Given a search query, retrieve Swiss parliamentary affairs that match it\nQuery: "
torch.set_num_threads(2)
model = SentenceTransformer("/model", device="cpu")
lock = threading.Lock()


class H(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"ok": True})

    def do_POST(self):
        try:
            n = int(self.headers.get("content-length", 0))
            q = json.loads(self.rfile.read(min(n, 4096)))["q"][:500]
        except Exception:
            return self._send(400, {"error": "bad request"})
        with lock:
            v = model.encode([PROMPT + q], normalize_embeddings=True)[0]
        self._send(200, {"vector": [round(float(x), 6) for x in v]})

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()

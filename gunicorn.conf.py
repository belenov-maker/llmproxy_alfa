"""Gunicorn production config для PD-Proxy.

Multi-worker с uvicorn для async FastAPI.
"""

import multiprocessing
import os

# Число workers: 2 * CPU + 1 (для CPU-bound regex + FastJev)
workers = int(os.getenv("PD_PROXY_WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 8)))
worker_class = "uvicorn.workers.UvicornWorker"
bind = f"0.0.0.0:{os.getenv('PD_PROXY_PORT', '8080')}"

# Timeouts
timeout = 120  # Для больших текстов + LLM proxy
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("PD_PROXY_LOG_LEVEL", "info")

# Preload для shared model loading (FastJev)
preload_app = False  # FastJev lazy-init per worker (thread-safe singleton)

# Max requests per worker (restart для утечек памяти)
max_requests = 10000
max_requests_jitter = 1000

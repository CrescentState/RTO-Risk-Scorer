# Gunicorn configuration for production
# Used by: gunicorn -c gunicorn.conf.py main:app

import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
# Rule of thumb: 2-4 workers per CPU core, but cap for container environments
workers = int(os.getenv("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2, 8)))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100

# Timeouts
timeout = 60
graceful_timeout = 30
keepalive = 5

# Restart workers after this many requests (memory leak protection)
# max_requests = 1000
# max_requests_jitter = 100

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "rto-risk-scorer"

# Server mechanics
preload_app = True
daemon = False
pidfile = "/tmp/gunicorn.pid"
tmp_upload_dir = None

# Security

# Security
limit_request_fields = 100
limit_request_field_size = 8190
limit_request_line = 4094

# SSL (if terminating at gunicorn)
# keyfile = "/app/ssl/key.pem"
# certfile = "/app/ssl/cert.pem"

def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Starting RTO Risk Scorer API")

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    server.log.info("Reloading RTO Risk Scorer API")

def worker_int(worker):
    """Called just after a worker exited on SIGINT or SIGQUIT."""
    worker.log.info("Worker received INT/QUIT signal")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    server.log.info(f"Spawning worker {worker.pid}")

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info(f"Worker {worker.pid} spawned")

def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    worker.log.info(f"Worker {worker.pid} initialized")

def worker_abort(worker):
    """Called when a worker received the SIGABRT signal."""
    worker.log.info(f"Worker {worker.pid} aborted")

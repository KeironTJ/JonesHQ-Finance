"""
Gunicorn Configuration for JonesHQ Finance
Production WSGI server settings
"""
import multiprocessing
import os

# Server Socket
bind = '127.0.0.1:8000'
backlog = 2048

# Worker Processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = 'sync'
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 60
keepalive = 5

# Logging
accesslog = '/home/joneshq/app/logs/gunicorn_access.log'
errorlog = '/home/joneshq/app/logs/gunicorn_error.log'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process Naming
proc_name = 'joneshq-finance'

# Server Mechanics
daemon = False
pidfile = '/home/joneshq/app/gunicorn.pid'
umask = 0o007
user = None
group = None
tmp_upload_dir = None

# SSL (handled by nginx, not needed here)
# keyfile = None
# certfile = None

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

def post_fork(server, worker):
    """Called after a worker has been forked"""
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def pre_fork(server, worker):
    """Called before a worker is forked"""
    pass

def pre_exec(server):
    """Called before a new master process is forked"""
    server.log.info("Forked child, re-executing.")

def when_ready(server):
    """Called when the server is ready"""
    server.log.info("Server is ready. Spawning workers")

def worker_int(worker):
    """Called when a worker receives an INT or QUIT signal"""
    worker.log.info("worker received INT or QUIT signal")

def worker_abort(worker):
    """Called when a worker fails to boot or times out"""
    worker.log.info("worker received SIGABRT signal")

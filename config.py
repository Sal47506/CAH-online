worker_class_options = {
    'sync': 'sync',
    'eventlet': 'eventlet',
    'gevent': 'gevent',
    'tornado': 'tornado'
}

bind = "0.0.0.0:$PORT"
worker_class = "eventlet"
workers = 1
threads = 1
timeout = 120
keepalive = 65
max_requests = 1200
max_requests_jitter = 200

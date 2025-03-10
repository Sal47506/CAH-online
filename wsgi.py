import gevent.monkey
gevent.monkey.patch_all()

import eventlet
eventlet.monkey_patch()

import os
from app import app, socketio

application = app

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        log_output=True,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True
    )

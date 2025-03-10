import eventlet
eventlet.monkey_patch()

from app import app, socketio

application = app

if __name__ == "__main__":
    socketio.run(
        app,
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        use_reloader=False,
        log_output=True,
        debug=False
    )

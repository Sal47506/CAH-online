import eventlet
eventlet.monkey_patch(os=True,
                     select=True,
                     socket=True,
                     thread=True,
                     time=True)

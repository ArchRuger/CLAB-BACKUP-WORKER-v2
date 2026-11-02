"""Keeps attacker-chosen text out of the container log.

uvicorn runs with --no-access-log, but its WebSocket layer and the websockets library still log every
handshake at INFO through the 'uvicorn.error' logger: the client address, the path and the query (all chosen
by the caller) and the open/close/reject lines. On an exposed, scanned VM that grows the log without bound.
install() drops those records; WARNING and above and the start-up lines pass untouched.
"""
import logging

LOGGER = 'uvicorn.error'


def keep(record):
    if record.levelno > logging.INFO:
        return True
    if record.levelno < logging.INFO:
        # At DEBUG the websockets library also writes every request header, the Cookie among them.
        return False
    try:
        text = record.getMessage()
    except Exception:
        return True   # a malformed record is the handler's to report, not this filter's to hide
    return not ('"WebSocket ' in text or text.startswith('connection '))


class HandshakeFilter(logging.Filter):
    clab_log_hygiene = True

    def filter(self, record):
        return keep(record)


def install():
    logger = logging.getLogger(LOGGER)
    if not any(getattr(item, 'clab_log_hygiene', False) for item in logger.filters):
        logger.addFilter(HandshakeFilter())

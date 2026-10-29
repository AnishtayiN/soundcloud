"""Privacy-aware diagnostics: never emit cookies, OAuth tokens or signed URLs."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import re
from urllib.parse import urlsplit

from . import util

LOG = logging.getLogger("scx")
_SECRET = re.compile(r"(?i)(oauth_token|track_authorization|access_token|client_id)=([^&\s;,]+)")
_HEADER = re.compile(r"(?i)(authorization|cookie)\s*[:=]\s*[^\r\n]+")
_URL = re.compile(r"(https?://[^\s?#]+)\?[^\s]+")


def safe_url(value):
    try:
        parts = urlsplit(str(value))
        if not parts.scheme or not parts.hostname:
            return "[local resource]"
        path = re.sub(r"(?i)/s-[A-Za-z0-9_-]+", "/[private]", parts.path)
        return "%s://%s%s" % (parts.scheme, parts.hostname, path)
    except (TypeError, ValueError):
        return "[invalid address]"


def safe_text(value):
    text = _SECRET.sub(lambda m: m.group(1) + "=[redacted]", str(value))
    text = _HEADER.sub(lambda m: m.group(1) + ": [redacted]", text)
    return _URL.sub(lambda m: m.group(1) + "?[redacted]", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        # HTTP client exceptions may contain the entire signed request URL.
        # Format the message only, never the unredacted exception traceback.
        message = safe_text(record.getMessage())
        return "%s %s %s" % (self.formatTime(record, "%H:%M:%S"), record.levelname, message)


def configure():
    if LOG.handlers:
        return LOG
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    try:
        handler = RotatingFileHandler(os.path.join(util.config_dir(), "soundcloudx.log"),
                                      maxBytes=512 * 1024, backupCount=1, encoding="utf-8")
    except (OSError, IOError):
        handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter())
    LOG.addHandler(handler)
    return LOG


def failed(operation, error, url=None):
    address = (" " + safe_url(url)) if url else ""
    status = getattr(getattr(error, "response", None), "status_code", None)
    detail = (" HTTP %s" % status) if status else ""
    LOG.warning("%s failed%s%s (%s)", operation, address, detail,
                type(error).__name__)


configure()

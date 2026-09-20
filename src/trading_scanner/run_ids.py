"""Readable local run identifiers shared by CLI and future web jobs."""
from datetime import datetime
import uuid
import re


def new_run_id(now=None):
    """Local minute prefix plus randomness prevents same-minute/DST collisions."""
    stamp = datetime.now().astimezone() if now is None else now
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("RUN_TIME_TIMEZONE_REQUIRED")
    return stamp.strftime("%Y%m%d%H%M") + "-" + uuid.uuid4().hex[:12]


def valid_run_id(value):
    return isinstance(value, str) and re.fullmatch(r"(?:[a-f0-9]{32}|[0-9]{12}-[a-f0-9]{12})", value) is not None

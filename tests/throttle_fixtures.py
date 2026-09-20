"""Use actual feedback/files/logic with virtual time in synthetic integration tests."""
from contextlib import contextmanager
from unittest.mock import patch
from trading_scanner.throttling import Governor

@contextmanager
def virtual_throttle_time():
    original = Governor.__init__
    current = [1800000000.0]
    def sleep(seconds):
        current[0] += seconds
    def init(self, *args, **kwargs):
        kwargs.setdefault('clock', lambda: current[0])
        kwargs.setdefault('wall', lambda: current[0])
        kwargs.setdefault('sleep', sleep)
        original(self, *args, **kwargs)
    with patch.object(Governor, '__init__', init):
        yield

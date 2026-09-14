"""Run only reviewed synthetic tests: python3 -I -S tools/test_offline.py.

Install the boundary before test collection. No subprocesses can escape it.
This is a guard for reviewed Python, not a sandbox for hostile/native code.
"""
from pathlib import Path
import os
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / "artifacts" / "test-tmp"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
TEMP = tempfile.TemporaryDirectory(prefix="synthetic-", dir=TEMP_ROOT)
STDLIB = Path(os.__file__).resolve().parent
READ_ROOTS = (ROOT / "src", ROOT / "tests", ROOT / "config", Path(TEMP.name), STDLIB)
WRITE_ROOTS = (Path(TEMP.name),)


class DeniedEnvironment(dict):
    def __getitem__(self, key):
        raise PermissionError("OFFLINE_ENVIRONMENT_DENIED")

    def get(self, key, default=None):
        raise PermissionError("OFFLINE_ENVIRONMENT_DENIED")

    def __iter__(self):
        raise PermissionError("OFFLINE_ENVIRONMENT_DENIED")

    def __contains__(self, key):
        raise PermissionError("OFFLINE_ENVIRONMENT_DENIED")

    def keys(self):
        raise PermissionError("OFFLINE_ENVIRONMENT_DENIED")

    def items(self):
        raise PermissionError("OFFLINE_ENVIRONMENT_DENIED")

    def values(self):
        raise PermissionError("OFFLINE_ENVIRONMENT_DENIED")


def audit_guard(event, args):
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn", "ctypes.", "os.posix_spawn")) or event in {
            "os.system", "os.fork", "os.forkpty", "os.putenv", "os.unsetenv"}:
        raise PermissionError("OFFLINE_OPERATION_DENIED")
    if event == "open":
        if not isinstance(args[0], (str, bytes, os.PathLike)):
            raise PermissionError("OFFLINE_FILE_DESCRIPTOR_DENIED")
        path = Path(os.fsdecode(args[0])).resolve()
        writing = bool(args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        allowed = WRITE_ROOTS if writing else READ_ROOTS
        if not any(path == r or r in path.parents for r in allowed):
            raise PermissionError("OFFLINE_FILE_DENIED")
        if "site-packages" in path.parts or "dist-packages" in path.parts:
            raise PermissionError("OFFLINE_DEPENDENCY_DENIED")


# Replace mappings without inspecting their previous contents. -I -S disables
# environment-based Python configuration and site/startup hook execution.
os.environ = DeniedEnvironment()
if hasattr(os, "environb"):
    os.environb = DeniedEnvironment()
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))
sys.addaudithook(audit_guard)

# Tests receive only a synthetic directory and the public guard, not real paths.
import types
boundary = types.ModuleType("offline_boundary")
boundary.temp = Path(TEMP.name)
boundary.guard = audit_guard
sys.modules["offline_boundary"] = boundary
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

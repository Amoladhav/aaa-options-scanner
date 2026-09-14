"""Default discovery must not bypass the mandatory offline runner."""
import sys

if "offline_boundary" not in sys.modules:
    raise RuntimeError("Run tests with: python3 -I -S tools/test_offline.py")

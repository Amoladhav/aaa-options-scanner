"""Optional in-process suite: python3 -I -S tools/test_web.py --deps DIRECTORY.

No site initialization, sockets, subprocesses, real environment or user DB access.
Allow only reviewed pinned package subtrees, never the full site-packages folder.
Click's native Windows console adapter is replaced; real console I/O is not tested.
"""
from pathlib import Path
import os
import sys
import subprocess
import socket
import tempfile
import unittest
import types

ROOT = Path(__file__).resolve().parents[1]
if len(sys.argv)!=3 or sys.argv[1]!='--deps':
    raise SystemExit('Usage: python -I -S tools/test_web.py --deps DIRECTORY')
DEPS = Path(sys.argv[2]).resolve()
PINS = {'flask':'3.1.3','werkzeug':'3.1.8','jinja2':'3.1.6','markupsafe':'3.0.3',
        'itsdangerous':'2.2.0','click':'8.5.0','blinker':'1.9.0','waitress':'3.0.2'}
for name, version in PINS.items():
    metadata=DEPS/f'{name}-{version}.dist-info/METADATA'
    if not metadata.is_file() or f'Version: {version}\n' not in metadata.read_text(encoding='utf-8'):
        raise SystemExit('WEB_DEPENDENCY_VERSION_MISMATCH')
TEMP_ROOT=ROOT/'artifacts/test-tmp';TEMP_ROOT.mkdir(parents=True,exist_ok=True)
TEMP=tempfile.TemporaryDirectory(prefix='web-synthetic-',dir=TEMP_ROOT)
STDLIB=Path(os.__file__).resolve().parent
PACKAGE_ROOTS=tuple(DEPS/name for name in PINS)+tuple(DEPS/f'{name}-{v}.dist-info' for name,v in PINS.items())
READ_ROOTS=(ROOT/'src',ROOT/'web_tests',ROOT/'config',Path(TEMP.name),STDLIB)+PACKAGE_ROOTS

class SyntheticEnvironment(dict):
    # Flask's debug helper is read during app construction. This is a fixed
    # synthetic setting, not a read from the replaced process environment.
    def get(self,key,default=None):
        if key == 'FLASK_DEBUG':
            return '0'
        if key == 'PYREPL_TRACE':
            return None
        # Python 3.11 platform.system() also probes machine architecture on
        # Windows. Report it as unknown: Waitress only needs the OS name.
        # Never consult the real environment or invent an x86/ARM architecture.
        if key in ('PROCESSOR_ARCHITEW6432', 'PROCESSOR_ARCHITECTURE'):
            return ''
        raise PermissionError('OFFLINE_ENVIRONMENT_DENIED')
    def __getitem__(self,key):
        raise PermissionError('OFFLINE_ENVIRONMENT_DENIED')
    def __iter__(self):
        raise PermissionError('OFFLINE_ENVIRONMENT_DENIED')
    def __contains__(self,key):
        raise PermissionError('OFFLINE_ENVIRONMENT_DENIED')
    def keys(self):
        raise PermissionError('OFFLINE_ENVIRONMENT_DENIED')
    def items(self):
        raise PermissionError('OFFLINE_ENVIRONMENT_DENIED')
    def values(self):
        raise PermissionError('OFFLINE_ENVIRONMENT_DENIED')

def guard(event,args):
    if event.startswith(('socket.','subprocess.','os.exec','os.spawn','ctypes.','os.posix_spawn')) or event in {'os.system','os.fork','os.forkpty','os.putenv','os.unsetenv'}:
        raise PermissionError('OFFLINE_OPERATION_DENIED')
    if event=='sqlite3.connect' and args[0]!=':memory:':
        path=Path(os.fsdecode(args[0])).resolve()
        if Path(TEMP.name) not in path.parents:
            raise PermissionError('OFFLINE_DATABASE_DENIED')
    if event=='open':
        if not isinstance(args[0],(str,bytes,os.PathLike)):
            raise PermissionError('OFFLINE_FILE_DESCRIPTOR_DENIED')
        path=Path(os.fsdecode(args[0])).resolve()
        writing=bool(args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        roots=(Path(TEMP.name),) if writing else READ_ROOTS
        if not any(path==r or r in path.parents for r in roots):
            raise PermissionError('OFFLINE_FILE_DENIED')
        if ('site-packages' in path.parts or 'dist-packages' in path.parts) and not any(r in path.parents for r in PACKAGE_ROOTS):
            raise PermissionError('OFFLINE_DEPENDENCY_DENIED')

os.environ=SyntheticEnvironment()
if hasattr(os,'environb'):
    os.environb=SyntheticEnvironment()
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'src'),str(DEPS)]
sys.addaudithook(guard)
# Click 8.5.0's _compat imports this one function on Windows. Route tests do
# not exercise native console I/O: use its ordinary-stream fallback instead of
# loading kernel32/shell32 via ctypes. Install on every OS so the substitute is
# regression-tested on Linux too. Never preload native APIs or relax the guard.
console=types.ModuleType('click._winconsole')
def synthetic_console_stream(stream, encoding, errors):
    return None
console._get_windows_console_stream=synthetic_console_stream
sys.modules['click._winconsole']=console
boundary=types.ModuleType('offline_boundary');boundary.temp=Path(TEMP.name);boundary.guard=guard
sys.modules['offline_boundary']=boundary
suite=unittest.defaultTestLoader.discover(str(ROOT/'web_tests'),pattern='test_*.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

import os
import socket
import sqlite3
import subprocess
import sys
import unittest
from offline_boundary import temp

class WebBoundaryTests(unittest.TestCase):
    def test_guards_remain_active(self):
        for operation in (lambda:socket.socket(),lambda:subprocess.run(['echo','denied']),
                          lambda:os.environ.get('SCANNER_OTA_TOKEN'),lambda:open('/tmp/not-allowed','rb'),
                          lambda:sqlite3.connect(temp.parent/'not-test.sqlite3'),
                          lambda:sys.audit('ctypes.dlopen', 'synthetic-denied-library'),
                          lambda:sys.audit('ctypes.dlsym', None, 'synthetic-denied-symbol')):
            with self.assertRaises(PermissionError):
                operation()
    def test_reviewed_imports(self):
        import flask,waitress,jinja2

    def test_windows_architecture_probes_are_synthetic(self):
        import platform
        from unittest.mock import patch
        for key in ('PROCESSOR_ARCHITEW6432', 'PROCESSOR_ARCHITECTURE'):
            self.assertEqual(os.environ.get(key, 'must-not-be-used'), '')
            with self.assertRaises(PermissionError):
                os.environ[key]
        for key in ('SCANNER_OTA_TOKEN', 'PROCESSOR_IDENTIFIER', 'UNKNOWN_SETTING'):
            with self.assertRaises(PermissionError):
                os.environ.get(key, '')
        # Exercise the actual fallback on Python versions that expose it,
        # including Linux hosts; no Windows impersonation or real env reads.
        if hasattr(platform, '_get_machine_win32'):
            # Newer Python versions may try WMI before the environment fallback.
            with patch.object(platform, '_wmi_query', create=True,
                              side_effect=OSError('Synthetic WMI unavailable')):
                self.assertEqual(platform._get_machine_win32(), '')
        if sys.platform == 'win32':
            with patch.object(platform, '_uname_cache', None):
                self.assertEqual(platform.system(), 'Windows')

    def test_console_substitute_uses_plain_stream_fallback(self):
        from click._winconsole import _get_windows_console_stream
        class UnusableStream:
            def fileno(self):
                raise AssertionError('Native console inspection must not run')
        self.assertIsNone(_get_windows_console_stream(UnusableStream(), 'utf-8', 'strict'))
        if sys.platform == 'win32':
            from click import _compat
            self.assertIs(_compat._get_windows_console_stream, _get_windows_console_stream)

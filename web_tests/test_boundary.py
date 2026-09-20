import os
import socket
import sqlite3
import subprocess
import unittest
from offline_boundary import temp

class WebBoundaryTests(unittest.TestCase):
    def test_guards_remain_active(self):
        for operation in (lambda:socket.socket(),lambda:subprocess.run(['echo','denied']),
                          lambda:os.environ.get('SCANNER_OTA_TOKEN'),lambda:open('/tmp/not-allowed','rb'),
                          lambda:sqlite3.connect(temp.parent/'not-test.sqlite3')):
            with self.assertRaises(PermissionError):
                operation()
    def test_reviewed_imports(self):
        import flask,waitress,jinja2

"""Run identifiers remain readable, unique and compatible with logging."""
from datetime import datetime, timezone, timedelta
import unittest
from offline_boundary import temp
from trading_scanner.run_ids import new_run_id
from trading_scanner.progress import RunProgress


class RunIdTests(unittest.TestCase):
    def test_local_minute_and_same_minute_uniqueness(self):
        stamp=datetime(2026,9,20,5,7,tzinfo=timezone(timedelta(hours=-7)))
        ids={new_run_id(stamp) for _ in range(100)}
        self.assertEqual(len(ids),100)
        for value in ids:
            self.assertRegex(value,r'^202609200507-[a-f0-9]{12}$')
        with self.assertRaises(ValueError):
            new_run_id(datetime(2026,9,20))

    def test_logger_accepts_new_and_legacy_ids(self):
        for value in (new_run_id(), 'a'*32):
            progress=RunProgress(temp/'run-id-logs',value,'dashboard-demo','synthetic','b'*64)
            self.assertEqual(progress.path.name,value+'.jsonl')
        with self.assertRaises(ValueError):
            RunProgress(temp/'run-id-logs','../escape','dashboard-demo','synthetic','b'*64)

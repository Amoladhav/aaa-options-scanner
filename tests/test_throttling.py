"""Synthetic policy/HTTP tests with virtual time and isolated local files."""
from datetime import datetime, timezone
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from offline_boundary import temp
from trading_scanner.core import DataError
from trading_scanner.throttling import Governor, retry_deadline
from trading_scanner.progress import RunProgress
from trading_scanner.public_transport import session_class, read_constituents


class ThrottleTests(unittest.TestCase):
    def setUp(self):
        self.now = 1800000000.0
        self.sleeps = []
        self.directory = temp / self._testMethodName
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
    def governor(self, provider='ota', **kwargs):
        return Governor(self.directory, provider, clock=lambda: self.now, wall=lambda: self.now,
                        sleep=self.sleep, **kwargs)

    def test_pacing_and_persistent_slowdown_no_automatic_speedup(self):
        with self.governor() as g:
            times = []
            def fail():
                times.append(self.now)
                g.observe(429, '360')
                raise DataError('OTA_RATE_LIMITED')
            with self.assertRaisesRegex(DataError, 'OTA_RATE_LIMITED'):
                g.call(fail, retries=0)
            self.assertEqual(g.state['interval_seconds'], 10)
        with self.governor() as g:
            self.assertEqual(g.state['interval_seconds'], 10)
            g.call(lambda: times.append(self.now))
            self.assertGreaterEqual(times[1] - times[0], 360)
        saved = json.loads((self.directory / 'ota.json').read_text())
        self.assertEqual(saved['interval_seconds'], 10)
        self.assertEqual(saved['runs'], 2)
        histories = list((self.directory / 'history').glob('*.json'))
        self.assertEqual(len(histories), 2)
        self.assertTrue(all(json.loads(p.read_text())['fetch_duration_seconds'] >= 5 for p in histories))
        self.assertFalse((self.directory / 'ota.lock').exists())

    def test_retry_limit_and_circuit_prevents_further_requests(self):
        with self.governor('tradier-production') as g:
            calls = []
            def fail():
                calls.append(1)
                g.observe(503, '1')
                raise DataError('TRADIER_HTTP_ERROR')
            with self.assertRaises(DataError):
                g.call(fail)
            with self.assertRaises(DataError):
                g.call(fail)
            self.assertEqual(len(calls), 2)
            self.assertEqual(g.retries, 1)
            self.assertEqual(g.state['interval_seconds'], 8)

    def test_auth_never_retried_or_accelerated(self):
        with self.governor() as g:
            def fail():
                g.observe(403)
                raise DataError('OTA_AUTH_REJECTED')
            with self.assertRaisesRegex(DataError, 'OTA_AUTH_REJECTED'):
                g.call(fail)
            self.assertEqual(g.requests, 1)
            self.assertEqual(g.retries, 0)
            self.assertEqual(g.state['interval_seconds'], 5)

    def test_large_retry_after_stops_without_shortening_deadline(self):
        with self.governor() as g:
            g.observe(429, '7200')
            with self.assertRaisesRegex(DataError, 'THROTTLE_COOLDOWN_ACTIVE'):
                g.call(lambda: self.fail('must not issue request'))
            self.assertEqual(g.requests, 0)
        self.assertEqual(retry_deadline('bad', self.now), self.now)
        date = datetime.fromtimestamp(self.now + 100, timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
        self.assertEqual(retry_deadline(date, self.now), self.now + 100)

    def test_lock_and_corrupt_feedback_fail_closed(self):
        with self.governor():
            with self.assertRaisesRegex(DataError, 'THROTTLE_BUSY'):
                with self.governor():
                    self.fail('parallel request session')
        (self.directory / 'ota.json').write_text('{"schema_version":1,"secret":"synthetic-private"}')
        with self.assertRaisesRegex(DataError, 'THROTTLE_STATE_INVALID'):
            with self.governor():
                self.fail('corrupt state accepted')
        self.assertFalse((self.directory / 'ota.lock').exists())

    def test_quota_feedback_can_only_slow_and_wait(self):
        with self.governor('tradier-production') as g:
            g.observe(200, available='0', expiry=str(self.now + 80), allowed='10')
            self.assertEqual(g.state['interval_seconds'], 7)
            g.call(lambda: None)
            self.assertGreaterEqual(sum(self.sleeps), 85)
            g.observe(200, available='120', allowed='120')
            self.assertEqual(g.state['interval_seconds'], 7)

    def test_cancellation_releases_lock_and_estimate_uses_actual_latency(self):
        tracker = RunProgress(self.directory / 'logs', 'a'*32, 'ota-fetch', 'ota', 'b'*64, stream=io.StringIO())
        try:
            tracker.start('ota_fetch', total=10)
            with self.governor(progress=tracker) as g:
                g.plan(10)
                first = tracker.forecast['remaining_seconds']
                g.call(lambda: self.sleep(50))
                g.unit_done()
                self.assertGreater(tracker.forecast['remaining_seconds'], first)
                self.assertIn('Estimated completion:', tracker.stream.getvalue())
                with self.assertRaises(KeyboardInterrupt):
                    g.call(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
            self.assertFalse((self.directory / 'ota.lock').exists())
        finally:
            tracker.close()

    def test_yahoo_session_paces_redirect_and_blocks_retries_after_denial(self):
        calls = []
        class Base:
            def request(self, method, url, **kwargs):
                calls.append((method, url, kwargs))
                return SimpleNamespace(status_code=302 if len(calls)==1 else 403,
                                       headers={'Location':'https://query1.finance.yahoo.com/next'}, close=lambda: None)
        with self.governor('yahoo') as g:
            session = session_class(Base, g)()
            with self.assertRaisesRegex(DataError, 'PUBLIC_ACCESS_REJECTED'):
                session.get('https://finance.yahoo.com/start')
            with self.assertRaises(DataError):
                session.get('https://finance.yahoo.com/start')
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(call[2]['allow_redirects'] is False for call in calls))
            self.assertEqual(g.requests, 2)
            self.assertEqual(sum(self.sleeps), 20)

    def test_direct_transports_supply_rate_feedback(self):
        from trading_scanner.tradier import request_json
        from trading_scanner.ota_fetch import fetch_page
        for provider in ('tradier-production', 'ota'):
            with self.governor(provider) as g:
                response = SimpleNamespace(status=429, getheader=lambda key: '1800' if key=='Retry-After' else None)
                connection = SimpleNamespace(request=lambda *a, **k: None, getresponse=lambda: response, close=lambda: None)
                module = 'tradier' if provider.startswith('tradier') else 'ota_fetch'
                with patch(f'trading_scanner.{module}.ssl.create_default_context'), patch(f'trading_scanner.{module}.http.client.HTTPSConnection',return_value=connection):
                    with self.assertRaises(DataError):
                        if provider == 'ota':
                            fetch_page([{'field':'optionable','valueFilter':'BOOLEAN','valueChoices':'Yes','criteria':'true'}], 'synthetic-local-input', governor=g)
                        else:
                            request_json('production','quote',{'symbols':'AAA','greeks':'false'},'synthetic-local-input',governor=g)
                self.assertGreaterEqual(g.state['cooldown_until'], self.now + 1700)
                self.assertEqual(g.rate_limits, 1)

    def test_interruption_outside_context_records_failure_and_releases_lease(self):
        with self.assertRaises(KeyboardInterrupt):
            with self.governor() as g:
                g.call(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertFalse((self.directory / 'ota.lock').exists())
        history = json.loads(next((self.directory / 'history').glob('*.json')).read_text())
        self.assertEqual(history['status'], 'interrupted_or_failed')
        self.assertEqual(history['http_requests'], 1)

    def test_wikipedia_rate_limit_is_observed_without_unbounded_retry(self):
        from urllib.error import HTTPError
        from unittest.mock import Mock
        opener = Mock()
        opener.open.side_effect = HTTPError('https://en.wikipedia.org/test', 429, 'limited', {'Retry-After':'1800'}, None)
        with self.governor('wikipedia') as g:
            with patch('trading_scanner.public_transport.urllib.request.build_opener', return_value=opener):
                with self.assertRaisesRegex(DataError, 'THROTTLE_COOLDOWN_ACTIVE'):
                    read_constituents('https://en.wikipedia.org/test', g)
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(g.rate_limits, 1)

    def test_progress_totals_include_both_public_providers(self):
        tracker = RunProgress(self.directory / 'logs', 'a'*32, 'refresh', 'public', 'b'*64, stream=io.StringIO())
        try:
            tracker.start('constituents')
            for provider in ('wikipedia', 'yahoo'):
                with self.governor(provider, progress=tracker) as g:
                    g.plan(1)
                    g.call(lambda: None)
                    g.unit_done()
            self.assertEqual(tracker.last_counts['http_requests'], 2)
            self.assertEqual(tracker.last_counts['throttle_wait_seconds'], 12)
            self.assertEqual(tracker.forecast['remaining_seconds'], 0)
        finally:
            tracker.close()

    def test_yahoo_external_redirect_stops_later_library_calls(self):
        class Base:
            def request(self, *args, **kwargs):
                return SimpleNamespace(status_code=302, headers={'Location':'https://example.com/'}, close=lambda: None)
        with self.governor('yahoo') as g:
            session = session_class(Base, g)()
            with self.assertRaisesRegex(DataError, 'PUBLIC_ACCESS_REJECTED'):
                session.get('https://finance.yahoo.com/start')
            with self.assertRaisesRegex(DataError, 'PUBLIC_ACCESS_REJECTED'):
                session.get('https://finance.yahoo.com/start')
            self.assertEqual(g.requests, 1)

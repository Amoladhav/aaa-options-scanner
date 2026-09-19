from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from offline_boundary import temp
from trading_scanner.cli import main
from trading_scanner.core import DataError
from trading_scanner.ota_config import parse_config, save_config, read_paste, MAX_INPUT

PASTE = '[{field: "optionable", valueFilter: "BOOLEAN", valueChoices: "Yes", criteria: "true"}]'


class OtaConfigTests(unittest.TestCase):
    def test_enter_submits_without_reading_eof(self):
        class OpenTerminal:
            def __init__(self, lines):
                self.lines = iter(lines)
            def readline(self, limit):
                try:
                    return next(self.lines)
                except StopIteration:
                    raise AssertionError('Attempted to wait for EOF')
        for text in (PASTE + '\n', json.dumps(parse_config(PASTE)['criteria'], indent=2) + '\n'):
            self.assertEqual(parse_config(read_paste(OpenTerminal(text.splitlines(keepends=True)))), parse_config(PASTE))

    def test_paste_string_brackets_escapes_and_limits(self):
        row = {'field':'sector', 'valueFilter':'SELECT', 'valueChoices':'bracket ] and quote " and slash \\'}
        text = json.dumps([row], indent=2) + '\n'
        self.assertEqual(parse_config(read_paste(io.StringIO(text)))['criteria'], [row])
        with self.assertRaises(DataError):
            read_paste(io.StringIO('[' + ' ' * MAX_INPUT))
        with self.assertRaises(DataError):
            parse_config(read_paste(io.StringIO('[\n')))

    def test_help_includes_paste_example(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            main(['ota-config', '--help'])
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn('no EOF is needed', output.getvalue())
        self.assertIn('"field":"optionable"', output.getvalue())

    def test_devtools_keys_and_json_roundtrip(self):
        config = parse_config(PASTE)
        self.assertEqual(config['criteria'][0]['criteria'], 'true')
        self.assertEqual(config, parse_config(json.dumps(config['criteria'])))

    def test_all_supported_filters_preserve_values(self):
        rows = [
            {'field': 'sector', 'valueFilter': 'SELECT', 'valueChoices': 'Example One,Example Two'},
            {'field': 'ivGauge', 'valueFilter': 'SELECT_CODED', 'valueChoices': '2,0', 'criteria': 'false'},
            {'field': 'last', 'valueFilter': 'RANGE_INSIDE', 'valueMin': 15, 'valueMax': 200},
            {'field': 'changePercent', 'valueFilter': 'RANGE_OUTSIDE', 'valueMin': -5, 'valueMax': -1},
            {'field': 'sma_50', 'valueFilter': 'COMPARE', 'valueChoices': 'sma_200', 'valueComparison': 'ABOVE', 'criteria': False},
        ]
        self.assertEqual(parse_config(json.dumps(rows))['criteria'], rows)

    def test_abbreviated_and_executable_inputs_rejected(self):
        for text in ['[{field: "sector",…}]', '[{field: "sector", ...}]',
                     '[process.exit()]', '0: ' + PASTE, PASTE + ' garbage',
                     '[{field: "last", valueFilter: "RANGE_INSIDE", valueMin: 1 2, valueMax: 30}]']:
            with self.subTest(text=text), self.assertRaises(DataError):
                parse_config(text)

    def test_ota_range_operator_choices_preserved(self):
        for kind in ('RANGE_INSIDE', 'RANGE_OUTSIDE'):
            row = {'field': 'volume', 'valueFilter': kind, 'valueMin': 100,
                   'valueMax': 1000, 'valueChoices': kind, 'criteria': 'false'}
            self.assertEqual(parse_config(json.dumps([row]))['criteria'], [row])
            row['valueChoices'] = 'SELECT'
            with self.assertRaises(DataError):
                parse_config(json.dumps([row]))

    def test_chat_escaped_underscore_rejected_without_modification(self):
        text = '[{"field":"sma\\_50","valueFilter":"COMPARE","valueChoices":"sma_200","valueComparison":"ABOVE"}]'
        with self.assertRaises(DataError):
            parse_config(text)

    def test_schema_rejection_and_duplicate_keys(self):
        base = json.loads(json.dumps(parse_config(PASTE)['criteria']))
        cases = [[], {'headers': {}}, base * 2,
                 [dict(base[0], unexpected='synthetic-private-marker')],
                 [dict(base[0], criteria='yes')], [dict(base[0], valueFilter='UNKNOWN')],
                 [dict(base[0], valueChoices=True)],
                 [{'field':'last', 'valueFilter':'RANGE_INSIDE', 'valueMin':20, 'valueMax':10}],
                 [{'field':'last', 'valueFilter':'RANGE_INSIDE', 'valueMin':True, 'valueMax':10}],
                 [{'field':'last', 'valueFilter':'RANGE_INSIDE', 'valueMin':0, 'valueMax':float('inf')}]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(DataError):
                parse_config(json.dumps(rows))
        with self.assertRaises(DataError):
            parse_config(PASTE.replace('field:', 'field: "duplicate", field:'))
        with self.assertRaises(DataError):
            parse_config(' ' * (MAX_INPUT + 1))

    def test_preview_apply_and_failed_update_preserve_config(self):
        root = temp / 'ota-config-cli'
        root.mkdir()
        destination = root / 'config' / 'ota-screener.json'
        with patch('sys.stdin', io.StringIO(PASTE)), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-config'], root), 0)
        self.assertFalse(destination.exists())
        with patch('sys.stdin', io.StringIO(PASTE)), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-config', '--apply'], root), 0)
        previous = destination.read_bytes()
        self.assertEqual(json.loads(previous), parse_config(PASTE))
        stdout = io.StringIO()
        with patch('sys.stdin', io.StringIO('synthetic-private-marker')), redirect_stdout(stdout):
            self.assertEqual(main(['ota-config', '--apply'], root), 1)
        self.assertEqual(previous, destination.read_bytes())
        self.assertNotIn('synthetic-private-marker', stdout.getvalue())
        for path in root.glob('artifacts/logs/*.jsonl'):
            self.assertNotIn('valueChoices', path.read_text())
            self.assertNotIn('synthetic-private-marker', path.read_text())

    def test_file_input_and_atomic_replace_failure(self):
        root = temp / 'ota-config-file'
        root.mkdir()
        source = root / 'criteria.txt'
        source.write_text(PASTE, encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-config', '--input', str(source), '--apply'], root), 0)
        destination = root / 'config' / 'ota-screener.json'
        before = destination.read_bytes()
        with patch('pathlib.Path.replace', side_effect=OSError('synthetic-error')):
            with self.assertRaises(OSError):
                save_config(parse_config(PASTE), destination)
        self.assertEqual(destination.read_bytes(), before)
        self.assertEqual(list(destination.parent.iterdir()), [destination])

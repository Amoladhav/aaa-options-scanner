"""Synthetic-only scanner checks; run with python3 -I -S tools/test_intake_scan.py."""
from pathlib import Path
import io
import json
import sys
import tarfile
import tempfile
import unittest
import zipfile


# This runner never loads incoming tests or site-packages. Deny network/process
# operations before importing our reviewed scanner; allow reads only in the
# interpreter installation, this tools directory, and the synthetic temp tree.
TOOLS = Path(__file__).resolve().parent
TEMP = tempfile.TemporaryDirectory(prefix="scanner-synthetic-")
ALLOWED = (TOOLS, Path(TEMP.name), Path(sys.base_prefix).resolve())


def offline_guard(event, args):
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn")) or event in {"os.system", "os.fork", "ctypes.dlopen", "ctypes.dlsym"}:
        raise PermissionError("OFFLINE_OPERATION_DENIED")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0]).resolve()
        if not any(path == root or root in path.parents for root in ALLOWED):
            raise PermissionError("OFFLINE_FILE_DENIED")


sys.addaudithook(offline_guard)
sys.path.insert(0, str(TOOLS))
import intake_scan


class IntakeScanTests(unittest.TestCase):
    def test_values_never_enter_report_or_review(self):
        source = Path(TEMP.name) / "source"
        source.mkdir()
        # Synthetic values are assembled so the scanner's own fixtures do not
        # resemble an accidentally committed credential.
        value = "synthetic" + "Credential123456789"
        (source / "config.txt").write_text('api_token = "' + value + '"\n', encoding="utf-8")
        review = Path(TEMP.name) / "review"
        report = intake_scan.scan(source, review)
        self.assertTrue(report["findings"])
        self.assertNotIn(value, json.dumps(report))
        self.assertNotIn(value, (review / "config.txt").read_text(encoding="utf-8"))
        self.assertEqual(set(report["findings"][0]), {"path", "line", "rule"})

    def test_empty_values_and_named_placeholders(self):
        self.assertEqual(intake_scan.findings('api_token = ""\napi_key = "YOUR_API_KEY"\n'), [])

    def test_query_bearer_private_key_and_overlap_redaction(self):
        token = "synthetic" + "Token12345"
        samples = ["https://example.invalid/?auth=" + token,
                   'Authorization: "Bearer ' + token + '"',
                   "-----BEGIN " + "PRIVATE KEY-----\nsynthetic\n-----END " + "PRIVATE KEY-----"]
        for sample in samples:
            with self.subTest(kind=sample[:8]):
                matches = intake_scan.findings(sample)
                self.assertTrue(matches)
                redacted = intake_scan.redact(sample, matches)
                self.assertNotIn(token, redacted)
                self.assertNotIn("synthetic", redacted)

    def test_archive_members_scanned_without_extraction(self):
        source = Path(TEMP.name) / "archives"
        source.mkdir()
        body = ('password = "' + 'synthetic' + 'Pass12345"').encode()
        with zipfile.ZipFile(source / "sample.zip", "w") as archive:
            archive.writestr("../../escape.txt", body)
        with tarfile.open(source / "sample.tar", "w") as archive:
            member = tarfile.TarInfo("entry.txt")
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
            link = tarfile.TarInfo("alias.txt")
            link.type = tarfile.LNKTYPE
            link.linkname = "entry.txt"
            archive.addfile(link)
        report = intake_scan.scan(source)
        self.assertEqual(report["summary"]["archive_members_scanned"], 3)
        self.assertEqual(report["coverage_gaps"], [])
        self.assertTrue(any(f["path"].endswith("!entry.txt") for f in report["findings"]))
        self.assertFalse((Path(TEMP.name) / "escape.txt").exists())

    def test_links_fail_closed(self):
        source = Path(TEMP.name) / "links"
        source.mkdir()
        try:
            (source / "link").symlink_to(source / "missing")
        except OSError:
            self.skipTest("Symlink creation unavailable on this platform")
        report = intake_scan.scan(source)
        self.assertEqual(report["coverage_gaps"][0]["rule"], "SYMLINK_NOT_FOLLOWED")

    def test_network_process_and_private_paths_denied(self):
        for event, args in [("socket.__new__", ()), ("subprocess.Popen", ()),
                            ("open", ("/outside-allowlist/synthetic-secret", "r", 0))]:
            with self.subTest(event=event), self.assertRaises(PermissionError):
                offline_guard(event, args)

    def test_review_cannot_overwrite_source(self):
        with self.assertRaises(ValueError):
            intake_scan.scan(TOOLS, TOOLS / "review")


if __name__ == "__main__":
    unittest.main()

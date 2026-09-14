"""Offline, value-suppressing intake scan. Never import or execute incoming files.

This deliberately conservative local scanner is a review aid, not proof that
credentials are absent. Reports contain locations/rules, never matched values.
Archives are read in memory with bounds; links are never followed or extracted.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import io
import json
import math
from pathlib import Path
import re
import tarfile
import zipfile

VERSION = "1"
MAX_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 10000
MAX_DEPTH = 3

# These rules are intentionally visible and dependency-free for local review.
# Capture groups identify only the portion to suppress in the review copy.
RULES = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|\Z)")),
    ("provider-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{20,})\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer-value", re.compile(r"(?i)\bBearer\s+(?P<value>[A-Za-z0-9._~+/-]{4,}=*)")),
    ("credential-assignment", re.compile(r'''(?ix)
        \b(?:[a-z][a-z0-9_]*_)?
        (?:api_?key|api_?token|access_?token|refresh_?token|auth_?token|token|password|passwd|client_?secret|secret_?key|authorization|cookie)
        ["']?\s*[:=]\s*["'](?P<value>[^"'\r\n]+)["']
    ''')),
    ("credential-unquoted", re.compile(r'''(?ix)
        \b(?:[a-z][a-z0-9_]*_)?
        (?:api_?key|api_?token|access_?token|refresh_?token|auth_?token|token|password|passwd|client_?secret|secret_?key)
        \s*[:=]\s*(?P<value>[A-Za-z0-9_./+~-]{8,}=*)(?=\s|$|[,;\x60])
    ''')),
    ("credential-query", re.compile(r"(?i)[?&](?:auth|token|api_?key|api_?token|access_?token|key|secret|password)=(?P<value>[^\s&#\"'<>\x60]+)")),
    ("url-userinfo", re.compile(r"(?i)https?://(?P<value>[^/@\s]+:[^/@\s]+)@")),
    ("credential-cli", re.compile(r'''(?ix)--(?:token|api-key|password|secret)\s+["']?(?P<value>[A-Za-z0-9_./+~-]{8,}=*)''')),
)
QUOTED_RANDOM = re.compile(r'''["'](?P<value>[A-Za-z0-9_+/=-]{32,})["']''')
PLACEHOLDERS = {"REDACTED", "YOUR_TOKEN", "YOUR_API_KEY", "YOUR_API_TOKEN", "YOUR_KEY", "TOKEN", "API_KEY", "CHANGEME", "PLACEHOLDER", "EXAMPLE", "NONE"}


@dataclass(frozen=True)
class Finding:
    line: int
    rule: str
    start: int
    end: int


def findings(text: str) -> list[Finding]:
    result = []
    for rule, pattern in RULES:
        for match in pattern.finditer(text):
            group = "value" if "value" in pattern.groupindex else 0
            value = match.group(group)
            if value.upper() in PLACEHOLDERS or value.startswith(("${", "<")):
                continue
            start, end = match.span(group)
            result.append(Finding(text.count("\n", 0, start) + 1, rule, start, end))
    for match in QUOTED_RANDOM.finditer(text):
        value = match.group("value")
        entropy = -sum((n / len(value)) * math.log2(n / len(value)) for n in Counter(value).values())
        if entropy >= 4.5 and any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
            start, end = match.span("value")
            result.append(Finding(text.count("\n", 0, start) + 1, "high-entropy-literal", start, end))
    return sorted(set(result), key=lambda f: (f.start, f.end, f.rule))


def redact(text: str, matches: list[Finding]) -> str:
    # Replace complete affected lines in this NON-EXECUTABLE review view. This
    # also prevents partial disclosure when several patterns overlap.
    hidden = set()
    for match in matches:
        first = text.count("\n", 0, match.start)
        last = text.count("\n", 0, max(match.start, match.end - 1))
        hidden.update(range(first, last + 1))
    return "".join("[REDACTED: inspect rule/location report]\n" if i in hidden else line
                   for i, line in enumerate(text.splitlines(keepends=True)))


def scan(source: Path, review_dir: Path | None = None) -> dict:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError("SOURCE_NOT_DIRECTORY")
    if review_dir is not None:
        review_dir = review_dir.resolve()
        if review_dir == source or source in review_dir.parents:
            raise ValueError("REVIEW_MUST_BE_OUTSIDE_SOURCE")
        if review_dir.exists():
            raise ValueError("REVIEW_DESTINATION_EXISTS")
        review_dir.mkdir(parents=True)
    report = {"scanner_version": VERSION, "files": [], "findings": [], "coverage_gaps": []}
    budget = [MAX_ARCHIVE_BYTES]

    def gap(path: str, rule: str) -> None:
        report["coverage_gaps"].append({"path": path, "rule": rule})

    def inspect(data: bytes, path: str, depth: int = 0, output: Path | None = None) -> None:
        if len(data) > MAX_BYTES:
            gap(path, "FILE_SIZE_LIMIT")
            return
        try:
            text = data.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = data.decode("latin-1")
            encoding = "binary-byte-patterns"
        matches = findings(text)
        report["files"].append({"path": path, "bytes": len(data), "scan": encoding})
        for match in matches:
            report["findings"].append({"path": path, "line": match.line, "rule": match.rule})
        is_archive = path.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz"))
        if output is not None and encoding == "utf-8" and not is_archive:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(redact(text, matches), encoding="utf-8")
        if not is_archive:
            return
        if depth >= MAX_DEPTH:
            gap(path, "ARCHIVE_DEPTH_LIMIT")
            return
        try:
            if path.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    members = archive.infolist()
                    if len(members) > MAX_MEMBERS:
                        gap(path, "ARCHIVE_MEMBER_LIMIT")
                        return
                    for member in members:
                        if member.is_dir():
                            continue
                        name = path + "!" + member.filename
                        if member.file_size > min(MAX_BYTES, budget[0]):
                            gap(name, "ARCHIVE_SIZE_LIMIT")
                            continue
                        budget[0] -= member.file_size
                        inspect(archive.read(member), name, depth + 1)
            else:
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                    for index, member in enumerate(archive):
                        if index >= MAX_MEMBERS:
                            gap(path, "ARCHIVE_MEMBER_LIMIT")
                            break
                        if member.isdir():
                            continue
                        name = path + "!" + member.name
                        if member.issym() or member.islnk():
                            # Resolve only the archive's internal member table;
                            # extractfile never opens a filesystem link target.
                            try:
                                stream = archive.extractfile(member)
                                linked = stream.read(min(MAX_BYTES, budget[0]) + 1) if stream is not None else b""
                                if len(linked) > min(MAX_BYTES, budget[0]):
                                    gap(name, "ARCHIVE_SIZE_LIMIT")
                                else:
                                    budget[0] -= len(linked)
                                    inspect(linked, name, depth + 1)
                            except Exception:
                                gap(name, "ARCHIVE_LINK_UNRESOLVED")
                            continue
                        if not member.isfile():
                            gap(name, "ARCHIVE_SPECIAL_MEMBER")
                            continue
                        if member.size > min(MAX_BYTES, budget[0]):
                            gap(name, "ARCHIVE_SIZE_LIMIT")
                            continue
                        budget[0] -= member.size
                        stream = archive.extractfile(member)
                        if stream is not None:
                            inspect(stream.read(MAX_BYTES + 1), name, depth + 1)
        except Exception:
            # Parser exceptions can contain attacker-controlled content.
            gap(path, "ARCHIVE_READ_FAILED")

    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        name = relative.as_posix()
        if path.is_symlink():
            gap(name, "SYMLINK_NOT_FOLLOWED")
        elif path.is_file():
            try:
                with path.open("rb") as stream:
                    data = stream.read(MAX_BYTES + 1)
                inspect(data, name, output=review_dir / relative if review_dir is not None else None)
            except OSError:
                gap(name, "FILE_READ_FAILED")
        elif not path.is_dir():
            gap(name, "SPECIAL_FILE_NOT_READ")
    report["summary"] = {"filesystem_files_scanned": sum("!" not in f["path"] for f in report["files"]),
                         "archive_members_scanned": sum("!" in f["path"] for f in report["files"]),
                         "findings": len(report["findings"]), "coverage_gaps": len(report["coverage_gaps"])}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path)
    args = parser.parse_args()
    try:
        report = scan(args.source, args.review_dir)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except Exception:
        print("SCAN_FAILED: inspect paths/permissions; no input content displayed")
        return 2
    print(json.dumps(report["summary"]))
    return 2 if report["coverage_gaps"] else (1 if report["findings"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())

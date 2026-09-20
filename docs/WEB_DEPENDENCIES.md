# Optional web dependency review

Reviewed 2026-09-20: Flask 3.1.3, Werkzeug 3.1.8, Jinja2 3.1.6, MarkupSafe 3.0.3,
itsdangerous 2.2.0, click 8.5.0, blinker 1.9.0 and Waitress 3.0.2. Exact pins are
in requirements-web.txt; core remains standard-library-only. This is a bounded
version/license/import review, not a full third-party security audit.

Official references: [Flask changes](https://flask.palletsprojects.com/en/stable/changes/),
[Flask security](https://flask.palletsprojects.com/en/stable/web-security/),
[Waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/),
[Werkzeug release metadata](https://pypi.org/project/Werkzeug/),
[Flask release metadata](https://pypi.org/project/Flask/),
[Waitress release metadata](https://pypi.org/project/waitress/).

Wheel METADATA/WHEEL and licenses were inspected before import. Pallets packages
use BSD-3-Clause licenses, blinker MIT and Waitress ZPL-2.1. Preserve dependency
license notices if redistributing packages. Current use installs optional packages
locally; no vendored copies are committed. No sdist/build hook was executed.
MarkupSafe includes its published native escaping extension and a Python fallback;
OS/Python-compatible wheels are required rather than building incoming code.

Reviewed transitive imports include Flask CLI/testing, Click, Jinja, Werkzeug and
Waitress. We never call Flask CLI, dotenv loading, reloader, debugger or remote
configuration. The runner allowlists only these pinned package subtrees; it does
not expose every installed package. It verifies version metadata and denies real
environment reads, network/subprocess access and SQLite outside temporary roots.
Flask's debug flag and Python 3.14's PYREPL_TRACE import read receive fixed synthetic
values; no real values are read. Default core tests retain their original guard.

Flask/Jinja were chosen for server-rendered pages and in-process route testing;
Waitress gives explicit loopback serving without the development server. No Node,
ASGI stack, ORM or external queue was added. These are project choices. Standard
Flask defaults are insufficient: the app explicitly checks Host/Origin/remote
address, protects POSTs, bounds input, disables proxy interpretation, escapes data,
restricts static assets and handles errors without raw exception text.

Evidence: Ubuntu/Python 3.14.4 core and optional route suites, plus a separate
synthetic loopback HTTP start/report/CSV/Host/stop smoke check. Native Windows,
macOS, browser visuals and Excel remain user acceptance, not library guarantees.

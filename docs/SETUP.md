# First local setup

Start with invented data: no trading account, API key, network fetch or application
packages are needed for the demo. This project is a personal local workspace; it
produces HTML files and offers an optional [localhost preview](LOCAL_WEB.md).
The no-package first demo below remains available.

For interactive help, ask your coding assistant:

> Follow docs/SETUP_AGENT.md. I want beginner guidance, one step at a time.

Use "guided" or "concise" if you prefer fewer explanations. The assistant should
ask your OS/shell and existing setup before giving platform-specific commands.
This document is also usable without any assistant.

## 1. Get to the project folder

Use a copy you are authorized to access. If you downloaded a ZIP, extract it first.
You do not need to create a GitHub repository or enable GitHub Actions to run it.
Do not run inside the ZIP or the INBOX reference directory.

On Windows, open the extracted project folder in File Explorer. Right-click in
the folder and choose **Open in Terminal** where available, then select PowerShell.
Alternatively open PowerShell from Start and use `Set-Location -LiteralPath` with
your actual folder path in quotes. The correct folder contains `run.py`, `README.md`
and `src`. Confirm in PowerShell:

```powershell
Test-Path .\run.py
```

Expected: `True`. If `False`, find the inner extracted folder containing `run.py`.

On macOS, open Terminal using Spotlight. Type `cd ` (including the space), drag the
project folder from Finder into Terminal, and press Enter. On Ubuntu/WSL, open its
terminal and change to the project folder with `cd` and your quoted folder path.
Confirm:

```bash
ls run.py
```

Expected: `run.py`. A terminal is simply the window where you enter these commands.
Copy commands only, not the Markdown fences or any `PS>`/`$` prompt characters.

## 2. Check Python

Python is the program that runs this project's code. Target versions are 3.11–3.14;
actual OS/dependency validation is narrower—see the [README](../README.md).

Windows PowerShell:

```powershell
python --version
```

If that command is unavailable, try `py --version`. Use whichever reports a
supported version consistently in the next step. If both are unavailable or a
Store alias opens instead, install a supported Python from the
[official Python downloads](https://www.python.org/downloads/), reopen PowerShell
and repeat the check. Do not assume the newest preview is supported.

macOS Terminal or Ubuntu/WSL:

```bash
python3 --version
```

If missing on macOS, use the official Python installer, reopen Terminal and retry.
On Ubuntu/WSL, obtain Python and its venv support through the distribution's normal
package manager; the setup agent should confirm the distribution/version before
suggesting package-install commands. Do not replace the operating system's Python.

Expected: a line such as `Python 3.14.x`. Resolve missing/unsupported Python before
continuing. The assistant should not ask you to show all environment variables.

## 3. Create a project environment

A virtual environment is a project-local Python environment that keeps optional
packages separate from other projects. If `.venv` already exists, first try its
version command below; do not blindly overwrite it. Windows, macOS and WSL need
separate environments—never copy a venv from another OS.

PowerShell, using the interpreter verified above:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe --version
```

If you verified `py` instead of `python`, use `py -m venv .venv` for the first line.

macOS Terminal or Ubuntu/WSL:

```bash
python3 -m venv .venv
.venv/bin/python --version
```

Expected: environment creation finishes without an error; the second command
prints the supported version. Creation itself may produce no output.
We invoke its interpreter directly, so activation is unnecessary and no PowerShell
execution-policy change is needed. This is supported by
[Python's venv documentation](https://docs.python.org/3/library/venv.html).

## 4. Generate and view the first dashboard

PowerShell:

```powershell
.\.venv\Scripts\python.exe -I -S run.py dashboard-demo
```

macOS Terminal or Ubuntu/WSL:

```bash
.venv/bin/python -I -S run.py dashboard-demo
```

Expected: current-step progress, a completed summary, a `Dashboard:` HTML path and
an `Agent review:` path. The `-I -S` flags isolate Python startup for this
standard-library demo. Optional data adapters later use the commands in README.

Open the printed `dashboard.html` file in your browser using File Explorer/Finder
or the browser's **Open File** command. WSL users can browse Linux files through
File Explorer's Linux entry and select the project folder. The page must say
**SYNTHETIC DEMO**: prices/options are invented. This confirms the local report
path works, not that a real provider connection works.

## 5. Choose the next step

Stop here if your goal was the demo. Otherwise choose one source at a time:

| Goal | Next instructions |
| --- | --- |
| Real public price history and master symbols | [README: download public data](../README.md#download-public-data-user-run) |
| OTA screener configuration and session token | [README: OTA criteria import](../README.md#paste-ota-screener-criteria-into-configuration) and the OTA sections that follow |
| Tradier single-symbol validation | [README: credential storage](../README.md#optional-local-credential-storage) and [chain plan](CHAIN_PLAN.md) |
| Tradier full-master fetch after a successful probe | [README: master-list collection](../README.md#master-list-drives-every-provider-join) |
| Run local development checks | [README: cross-platform checks](../README.md#cross-platform-checks) |

No package installation is needed for the demo. When selecting public data, review
`requirements-public.txt` and the platform-specific installation commands first.
Keyring is optional; hidden-prompt Tradier mode can avoid unavailable OS storage.
Provider requests are run by you, not by the assistant. Start with a single-symbol
probe before a long batch. Supply credentials only to the local hidden prompt;
blank-looking input while pasting is expected. Never paste a key or token into chat.

## Troubleshooting without starting over

| Symptom | First check |
| --- | --- |
| `run.py` not found | Current folder must be the extracted project root |
| `python`/`py`/`python3` not found | Install/check the supported interpreter for your OS, then reopen the terminal |
| `.venv` interpreter missing | Confirm environment creation succeeded and that Windows/WSL commands were not mixed |
| `venv` or `ensurepip` missing on Linux | Check the distribution's venv package for the chosen Python; do not use sudo pip |
| PowerShell activation blocked | Skip activation; use `.\.venv\Scripts\python.exe` directly |
| No compatible dependency wheel | Stop and review the supported Python/platform combination; do not remove wheels-only restrictions blindly |
| `TOKEN_STORE_UNAVAILABLE` | OS storage is unavailable; use the documented explicit hidden-prompt alternative where supported |
| Authentication rejected | Renew/check the credential locally and select the matching profile; do not send it to the assistant |
| No candidates | Check data coverage/age and filter outcomes; an empty shortlist is not proof setup failed |

Logs use your runtime machine's configured local timezone. Every run prints its
full-log/error-log paths; keep these files local. When asking an agent to investigate
a fetch, give the intended sanitized `Agent review:` path. For initial command-not-
found issues, a brief error category is enough; do not send raw captures or a full
terminal/environment dump. Avoid rerunning a long fetch merely to reproduce output.

Your setup is ready for the selected goal when you can repeat its command, locate
the output, understand whether it is synthetic or live, and find its diagnostics.
The next milestone is one verified real data source, then the combined dashboard.

## Optional: personalize a daily schedule

Scheduling stays disabled during the current C1–C6 local-web checkpoints. Skip
this section for that workflow; the guidance below applies only to a later
explicitly selected scheduling task.

After a manual provider run succeeds, choose your local time, named timezone and
whether to fetch OTA only or run public prices → OTA → dashboard. Follow
[SCHEDULING.md](SCHEDULING.md) for your platform's commands. These settings stay in
your ignored personal workspace; another user does not inherit them through Git.
A local worker must remain open and the computer awake. OTA needs a current session
token in the OS store; scheduling does not keep that session valid. The setup agent
can guide these choices at your preferred detail level.

## Optional environment injection

See [Infisical setup](SECRETS.md) for OS-specific installation, browser login,
profile-scoped injection and safe format checks. Complete the no-credential demo
first. All authentication and provider commands are user-run. Keep scheduling
disabled during the C1–C6 web checkpoints; no worker activation is implied.

## Returning to the localhost preview

Follow [LOCAL_WEB.md](LOCAL_WEB.md) for the selected OS and reuse your compatible
environment. The development handoff is [RESUME_PLAN.md](RESUME_PLAN.md); it records
completed steps so a new assistant does not restart setup. Current user evidence
is synthetic report visibility in Windows Chrome after WSL startup guidance.
Filters, saved-source quote coverage, Excel exports and realistic resource use
remain to be checked. Keep the server terminal open while using the app; Ctrl+C
in that terminal stops it. No automatic refresh, provider fetch or scheduler runs
in the preview. Target shared 8–16 GB machines with other trading tools open;
hardware acceptance remains pending.

C4 legacy history migration is an explicit user-run step after setup; see
[preview/import/rollback commands](CRS_HISTORY.md#explicit-legacy-import-c4b).
Opening the dashboard does not import old daily files. Verify the guarded suites
on the selected native platform before applying this storage upgrade to real data.

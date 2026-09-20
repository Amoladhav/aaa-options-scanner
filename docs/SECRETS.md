# Optional Infisical setup (C2)

Checked against official documentation on 2026-09-20. Commands below are user-run.
Agents do not install/login, inspect credentials or execute the wrappers. Begin
with [SETUP.md](SETUP.md): establish OS/shell, interpreter and preferred explanation
level, then produce a synthetic dashboard. Infisical is unnecessary for demos,
cached reports and the localhost preview. Scheduling stays disabled.

## Choose storage

Managed Infisical is the simpler optional route; it stores your secrets outside
this workspace. Choose its region/account deliberately. Self-hosting means you
operate authentication, TLS, upgrades and recovery; use the [official self-hosting
guide](https://infisical.com/docs/self-hosting/overview) as a separate advanced task.
The [Infisical repository](https://github.com/Infisical/infisical) distinguishes its
MIT core from separately licensed enterprise functionality. No account, subscription
or host is selected by this guide. Existing OS-store and hidden-prompt commands
remain supported if you prefer local storage.

## Install the CLI on your actual OS

These commands follow the [official CLI repository](https://github.com/Infisical/cli).
No installer was executed during documentation review. Review the downloaded Linux
script locally before authorizing its privileged steps. Do not share installer
output containing local configuration. Use your already configured package manager.

macOS with Homebrew already installed:

```bash
brew install infisical/get-cli/infisical
infisical --version
```

Native Windows PowerShell with Scoop already installed:

```powershell
scoop install infisical
infisical --version
```

Without Scoop, obtain your architecture's executable from [official
releases](https://github.com/Infisical/cli/releases), verify its published checksum,
extract it into a user-owned tools directory and add that directory to your user
PATH. Reopen PowerShell and run `infisical --version`. Ask for OS-specific guidance
if unsure; do not change execution policy or install a second package manager just
for this step.

Ubuntu/Debian or their WSL distributions, with curl available:

```bash
curl --fail --location --proto '=https' --tlsv1.2 https://artifacts-cli.infisical.com/setup.deb.sh --output /tmp/infisical-setup.deb.sh
less /tmp/infisical-setup.deb.sh
```

After reviewing the repository/key installation steps, the user runs:

```bash
sudo bash /tmp/infisical-setup.deb.sh
sudo apt-get update
sudo apt-get install infisical
infisical --version
```

Old Cloudsmith package URLs are obsolete. WSL installation/login is separate from
native Windows installation/login. Do not copy a credential store between them.

## Browser login and least-scope setup

In the repository folder, with your selected Infisical instance/region:

```text
infisical login
infisical init
```

Select the intended instance and project interactively. For a self-hosted domain,
follow [login's domain option](https://infisical.com/docs/cli/commands/login) using
your administrator's verified address; no machine token arguments are needed.
Login persists authentication in a local keyring. WSL without an available unlocked
keyring may fail: resolve that OS prerequisite or use scanner hidden-prompt mode.
Do not downgrade to plaintext storage to bypass it. `infisical init` associates
local project metadata; `.infisical.json` is ignored here. See [init](https://infisical.com/docs/cli/commands/init).

In your own Infisical console, create the following environment slugs and folder
paths for this guide. Store only the listed variable in each folder. Never paste
values into commands, chat or committed files. Use a role limited to the selected
project/environment/folder. Keep development empty for synthetic work.

| Environment slug | Folder | Secret name | Scanner profile |
| --- | --- | --- | --- |
| `dev` | `/scanner` | none | synthetic |
| `sandbox` | `/scanner/tradier` | `SCANNER_TRADIER_SANDBOX_TOKEN` | sandbox |
| `prod` | `/scanner/tradier` | `SCANNER_TRADIER_PRODUCTION_TOKEN` | production |
| `prod` | `/scanner/ota` | `SCANNER_OTA_TOKEN` | ota |

These slugs/paths are project setup choices. If you choose different ones, adapt
only the non-secret selectors. Do not place unrelated secrets in these folders.

## Verify format, then one explicit provider request

The [run command](https://infisical.com/docs/cli/commands/run) injects selected
secrets into a child process. These examples disable imports/expansion and personal
secret overrides to keep selection predictable. Do not add `--watch`: restarts
could repeat provider work. The scanner still explicitly selects its profile.

macOS or Ubuntu/WSL, using the environment created in SETUP.md:

```bash
infisical run --env=sandbox --path=/scanner/tradier --include-imports=false --expand=false --secret-overriding=false -- .venv/bin/python -I -S run.py credential-check --provider tradier --profile sandbox --credential-source env
infisical run --env=sandbox --path=/scanner/tradier --include-imports=false --expand=false --secret-overriding=false -- .venv/bin/python -I run.py tradier-probe --profile sandbox --symbol SPY --credential-source env
```

Native Windows PowerShell:

```powershell
infisical run --env=sandbox --path=/scanner/tradier --include-imports=false --expand=false --secret-overriding=false -- .\.venv\Scripts\python.exe -I -S run.py credential-check --provider tradier --profile sandbox --credential-source env
infisical run --env=sandbox --path=/scanner/tradier --include-imports=false --expand=false --secret-overriding=false -- .\.venv\Scripts\python.exe -I run.py tradier-probe --profile sandbox --symbol SPY --credential-source env
```

Run the second command only after format validation succeeds. Format validation
checks presence/printable syntax, not provider authentication or entitlements.
For production Tradier, change both `--env=prod` and `--profile production`; its
variable is separate. An OTA format check uses `--env=prod --path=/scanner/ota` and
`credential-check --provider ota --profile ota --credential-source env`. An OTA
fetch uses the same wrapper with `ota-fetch --profile ota --credential-source env`
only after screener setup. For Tradier batches, substitute `tradier-fetch` after
a successful probe and a user-run saved public master; see README.

These standard-library commands do not require a Python Infisical SDK or keyring
package. Optional IANA tzdata support may be needed by Tradier date selection;
follow the existing chain/setup guide if `DEPENDENCY_UNAVAILABLE` is reported.

## Recovery and evidence

| Result | User action |
| --- | --- |
| CLI login/keyring unavailable | Check the selected OS/instance and unlocked native store; use existing hidden prompt if needed |
| `CREDENTIAL_MISSING` | Check variable name and explicit environment/folder selection in your console |
| `CREDENTIAL_INVALID` | Replace malformed input locally; environment values cannot contain padding/newlines |
| Authentication rejected | Check provider/profile and renew/revoke at that provider; never switch profiles automatically |
| OTA expiry | Acquire a new session token through your authorized local process, update console, launch a new run |
| Infisical secret updated | Start a new wrapper process; an already running process keeps its existing environment |

Use `infisical logout` to end the local CLI session; consult [logout](https://infisical.com/docs/cli/commands/logout).
Provider revocation/rotation is separate from deleting a local copy. Infisical
cannot renew OTA sessions. Environment delivery is not a promise of memory-only
storage or immunity from debugging, subprocess inheritance or crash disclosure.
Do not dump the environment, export dotenv files, enable HTTP tracing or share raw
responses. Agents may read only the scanner's printed `artifacts/agent-review/`
summary. Infisical's own terminal output is not that allowlisted report.

C2 acceptance remains pending until the user completes one Tradier request through
this wrapper. Actual WSL, native Windows and macOS installation/login are each
unverified. Documentation review and synthetic CLI tests do not establish them.
Local catalog/web development can proceed without credentials while this user-run
acceptance stays open.

# 0002: Saved-data localhost preview before history/jobs

Implement C3a with Flask/Jinja plus Waitress and minimal server-rendered controls.
No frontend build or browser business logic is needed. `report_service` shares
composition with the CLI and owns complete-dataset selection and CSV exports.
Catalog IDs pin explicit sources; raw captures/credentials/SQL are never routes.
A separate synthetic workspace allows useful onboarding without any real data.

Bind only 127.0.0.1, validate exact Host/Origin, reject proxy headers, protect
mutations with session-bound CSRF and escape text. No debugger or provider controls.
A process-local busy lock serializes report creation. This is deliberately not a
job queue: C6 fetch/cancel requires durable claims, progress and restart recovery.

Existing HTML exports remain compatible and retain their current JavaScript view
controls. New table and filtered CSV share Python selection. The CLI's optional
prior daily history still works; web history input is explicitly deferred to C4.
Do not call CLI main from a request or implement another CRS/quote calculation.

C3a acceptance is route/service/CLI parity on fixtures plus a user browser/Excel
walkthrough of real saved inputs. In-process tests retain isolation; an explicit
synthetic HTTP smoke test is separate. Framework portability is not platform
validation. C4/C5/C6 remain open; C7 stays after C6 user acceptance.

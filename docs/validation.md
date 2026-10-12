# Validation record

Validated on 12 October 2026 using Python 3.12 in the development cloud environment.

- `python -m pytest -q`: **118 passed**, with no warnings. Includes the fictional lead-to-handover lifecycle, approval/payment gates, full upfront settlement, CRM validation, financial immutability, QA/revisions, maintenance scheduling, authentication/CSRF, uploads, email queue reliability with mocked SMTP, and backup/restore.
- `ruff check app tests scheduler`: passed.
- `ruff format --check app tests scheduler migrations`: passed.
- `flask --app run:create_app db upgrade`, `seed-templates`, and `db check`: passed; no migration drift.
- `python -m pip check`: no broken requirements.
- `bash scripts/setup.sh`: completed successfully on the prepared checkout, including repeatable migration and template initialization.
- Chromium browser review: 30 desktop views and five mobile views returned HTTP 200, with no JavaScript errors or page overflow. A real CSRF-protected login was exercised. Screens included CRM, all delivery workspaces, tasks, calendar, finance, documents, email, analytics and settings.
- Running Waitress: `/health` returned the expected JSON; `/login` returned an actual CSRF-enabled form.
- Dedicated scheduler: persisted scan jobs completed; a second process was rejected by the instance lock.

The dashboard screenshot uses a separate, clearly labeled fictional demonstration database. The primary environment database contains default templates and scheduler records, without a default administrator or sample client records.

Real SMTP delivery was **not tested**: no provider credentials were supplied. Test mode and mocked transport tests verified local queue behavior, TLS configuration, retries and uncertain-outcome handling. Hosting, electronic signatures, bank/payment-provider processing, and external client website deployment are separate operations; the CRM records their reviewed evidence. Granular team roles and client portal access are outside the current administrator-only release.

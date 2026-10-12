# Deployment and operations

## Local prerequisites and installation

Use Python 3.12, a virtual environment, and a supported operating system. The project uses Flask, SQLAlchemy, SQLite, Flask-Migrate, Flask-Login, Flask-WTF, APScheduler, yagmail, and ReportLab. ReportLab generates PDF documents without requiring a system HTML renderer. A DejaVu Sans system font improves PDF character coverage when available.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
flask --app run:create_app db upgrade
flask --app run:create_app seed-templates
flask --app run:create_app create-admin --email admin@example.com --name "Administrator"
flask --app run:create_app run --host 127.0.0.1 --port 5000
```

On Windows, activate with `.venv\Scripts\activate` for the web application; use WSL for the full web/scheduler workflow because the scheduler requires POSIX file locking. Use `requirements.txt` if test and lint tools are unnecessary. The administrator command prompts securely for a password; a securely injected `ADMIN_PASSWORD` can also supply it for unattended setup. No user account or password is generated automatically.

Each managed cloud task already has an isolated checkout. Use that checkout for development; a second Git worktree is unnecessary unless specifically requested.

## Environment configuration

Copy `.env.example` to `.env` and set values locally. Keep this file out of source control. The application reads environment variables with python-dotenv; actual secrets belong in your hosting platform's secret configuration.

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development` for local use, `production` for hosted operation. |
| `SECRET_KEY` | Stable, unpredictable session/CSRF secret. Production requires at least 32 characters. |
| `DATABASE_URL` | SQLAlchemy connection URL; default `sqlite:///webdev_crm.sqlite3` is relative to Flask's instance directory. |
| `BUSINESS_TIMEZONE` | IANA display timezone; default `Asia/Manila`. |
| `DEFAULT_CURRENCY` | Default project currency, `PHP`. |
| `SESSION_COOKIE_SECURE` | Use `true` for HTTPS production, `false` only for local HTTP development. |
| `EMAIL_TEST_MODE` | Defaults to `true`. Must be `false` as well as the Email Center test-mode setting before live SMTP is permitted. |
| `SMTP_HOST` | SMTP hostname; Gmail-compatible default is `smtp.gmail.com`. |
| `SMTP_PORT` | Default `465` uses implicit TLS; other supported ports require STARTTLS. |
| `SMTP_USER` / `SMTP_PASSWORD` | SMTP account and provider-issued application credential, supplied privately. |
| `AUTOMATIONS_PAUSED` | Pause scheduled automation without deleting records. |
| `RATELIMIT_STORAGE_URI` | Default `memory://` for one local process; use shared supported storage for multiple web processes. |

Generate a secret without committing it:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Development creates a private persisted key under the instance directory if a key is absent. Changing a key invalidates existing sessions. Never put client passwords, hosting tokens, SMTP credentials, or real secrets into business notes, generated documents, demo data, or source code.

## Database migrations

Initialize or update a database with:

```bash
flask --app run:create_app db upgrade
flask --app run:create_app db current
```

When changing models during development, create and inspect a migration:

```bash
flask --app run:create_app db migrate -m "Describe the schema change"
flask --app run:create_app db upgrade
```

Review migration code and back up existing data before applying it. `init-db` is a development convenience, not a replacement for production migrations. SQLite foreign keys are enabled for application connections. Prefer a local disk with reliable file locking; do not share a SQLite file across independent hosts.

## Web process

The Flask development server is appropriate for local use. For a persistent single-host installation, use Waitress behind an HTTPS reverse proxy:

```bash
waitress-serve --listen=127.0.0.1:5000 --call run:create_app
```

Configure `APP_ENV=production`, a stable `SECRET_KEY`, and `SESSION_COOKIE_SECURE=true`. Terminate HTTPS at the proxy and restrict the application port to the proxy or local machine. Run as a dedicated operating-system user with private permissions on `.env`, the database, uploads, backups, and logs. Do not enable Flask debugging for shared or production service.

The application initially supports a single administrator. The role field and server-side authorization deny non-administrator access; creating a viewer row does not establish a supported client portal.

## Scheduler process

Start one dedicated process from the repository root with the same environment and database as the web process:

```bash
python -m scheduler
```

The scheduler uses persistent database job records and a process lock. Keep it separate from web workers, and run only one instance per database. The web application does not quietly start a second scheduler. Repeated scans use event keys and unique constraints to avoid duplicate generated work. Scheduled actions generate reviewable records; they do not independently approve contracts, verify payments, or deploy websites.

The scheduler cannot execute while its machine or process is off. For continuous operation, use a service manager to restart it on boot and after failure. Inspect automation settings and execution records after a shutdown; overdue work may be processed on the next scan. Avoid multiple application hosts sharing a scheduler lock or SQLite database.

A minimal Linux service definition can use the same dedicated account and private environment file as the web service. Replace paths and the service account before installation:

```ini
[Unit]
Description=Hanami scheduler
After=network.target

[Service]
Type=simple
User=hanami
WorkingDirectory=/srv/hanami
EnvironmentFile=/srv/hanami/.env
ExecStart=/srv/hanami/.venv/bin/python -m scheduler
Restart=on-failure
RestartSec=10
UMask=0077

[Install]
WantedBy=multi-user.target
```

Use a separate service whose `ExecStart` runs Waitress for the web server. Review service-manager behavior, log retention, filesystem permissions, restart handling, and backup jobs in your own deployment.

## Email test procedure

1. Keep `EMAIL_TEST_MODE=true`. Create a draft to an address you control, inspect its recipient and rendered content, approve it, and queue it.
2. Run the scheduler and confirm that the Email Center records simulated delivery. Simulation must not be interpreted as real delivery.
3. To verify live SMTP, privately configure the account, provider application password, hostname, and TLS port. Gmail accounts typically require an application password or another provider-supported SMTP credential. The application does not provision Google accounts or OAuth credentials.
4. Disable test mode both in the environment and the application setting, then restart affected processes. Confirm that the UI reports live mode.
5. Create a new harmless message to your own address, explicitly approve it, and queue it. Verify the persisted send outcome and receipt in your mailbox before using client addresses.
6. Restore test mode during development. Do not reuse a simulated queue record as evidence that live SMTP works.

Only approved drafts may be queued. Connection failures receive bounded retry handling; an ambiguous failure after a send attempt is retained for review to reduce duplicate messages. Check the provider's sent/log records before manually retrying an uncertain delivery. No automated test should send actual mail.

SMTP is unverified until the procedure succeeds with your own credentials. Network restrictions in managed cloud environments may also require allowed destinations for your SMTP host and port. Configure these through the supported environment settings; do not disable TLS or bypass network policy.

## Backup and restore

Backups contain sensitive client and business data. Store them privately, encrypt off-host copies, and document an appropriate retention schedule. A backup is useful only after a successful restore drill.

Stop or pause web and scheduler writes while creating an archive so uploads stay consistent with the database snapshot:

```bash
flask --app run:create_app backup --output /private/backups/hanami.zip
```

For a restore, stop the web process and scheduler first. Verify that the archive came from a trusted source, preserve the current instance, then run:

```bash
flask --app run:create_app restore /private/backups/hanami.zip --yes
flask --app run:create_app db upgrade
```

Restore validates the archive and keeps a recovery copy of the existing database. Keep configuration and `SECRET_KEY` backed up separately using your secrets-management process; do not assume they are included with business data. Start the application and scheduler, sign in, verify representative clients, invoice balances, document downloads, and pending queue states. Restoring old queue state can reintroduce pending work, so review uncertain or previously delivered emails before resuming live sends.

For a privacy-aware business export:

```bash
flask --app run:create_app export-data --output /private/exports/hanami.json
```

Exports exclude user password hashes and secret settings, but still contain personal and commercial data. They are not a substitute for a complete database and uploaded-file backup.

## Account recovery and offboarding

Use `flask --app run:create_app reset-password --email EMAIL` to securely set a new password. The command invalidates prior sessions on their next request. Use `flask --app run:create_app set-user-active --email EMAIL --inactive` to remove access; `--active` reactivates an account. The last active administrator cannot be disabled. Audit these privileged operations and restrict access to the host terminal.

Every active administrator has full access to business records. Individual accounts provide attribution, but this release has no project-specific permissions or supported non-administrator portal.

## Retention and limited anonymization

`flask --app run:create_app anonymize-client CLIENT_ID --yes` clears contact/profile details from an archived client, related contacts, and converted leads after the configured retention age. `retention_days` defaults to 365 and cannot be below 30. Active projects and outstanding invoices block the command. The age is checked against the profile's last update; review the correct numeric client ID before running it.

Historical invoices, approvals, documents, email, logs, and backups remain intentionally preserved. This is a limited contact anonymization workflow, not complete legal erasure. Review the wider records and retention obligations separately; restrict who can run this irreversible operator command.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Login form expires | Reload it and retry. Confirm that all processes share the same stable session key and system time. |
| SQLite reports a missing table | Run `flask --app run:create_app db upgrade` with the same environment and database URL as the web server. |
| SQLite reports a locked database | Check for long writes, duplicate scheduler processes, disk health, and unsupported network filesystems. Keep transactions short. |
| A stage will not complete | Read its blocker list. Check current approvals, required evidence, executed contract, verified payments, and QA records. |
| Payment exists but balance remains | Verify the payment using independent evidence. Recording alone is intentionally insufficient. |
| Email remains queued | Confirm that the scheduler is running, automations are enabled, and the draft has been approved. |
| Email is simulated | Check both environment and application test-mode settings. Simulation does not contact SMTP. |
| SMTP fails | Check provider credentials, TLS port, network rules, and the persisted failure record. Never disable TLS verification. |
| Upload rejected | Use a permitted, nonempty PDF, PNG, JPEG, UTF-8 TXT/Markdown/CSV file within the 10 MB limit. An extension alone is insufficient. |
| PDF characters are missing | Install an appropriate Unicode font such as DejaVu Sans and regenerate the export. |
| Production refuses startup | Configure a stable `SECRET_KEY` of at least 32 random characters. |

## Validation and operational limits

Run `pytest -q` for backend, workflow, finance, email, security, and delivery tests. Tests use isolated databases and simulated or mocked SMTP. Run `ruff check app tests scheduler run.py` for static checks. A useful deployment smoke test covers sign-in, one lead, a generated document PDF, authenticated file download, a test-mode email, and backup/restore into a separate instance.

The CRM stores external acceptance evidence rather than collecting electronic signatures, records deployments rather than executing them, and records verified payments rather than processing transactions. Upload checks do not replace malware scanning. Local development rate-limit storage is per-process; configure shared storage before scaling web workers. Monitoring, offsite encryption, malware scanning, TLS hosting, and reliable service supervision are infrastructure responsibilities. No production SMTP account, domain, payment gateway, or hosting deployment is preconfigured.

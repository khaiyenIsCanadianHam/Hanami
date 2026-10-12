"""Administrator provisioning, fictional seed data and local recovery tools."""

from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import zipfile
import click
from email_validator import EmailNotValidError, validate_email
from flask import current_app
from app.extensions import db
from app.models import User, Client, Lead, Project, ApplicationSetting
from app.models.base import utcnow


def _database_path():
    if db.engine.url.get_backend_name() != "sqlite" or db.engine.url.database in {
        None,
        "",
        ":memory:",
    }:
        raise click.ClickException(
            "This command requires a file-backed SQLite database."
        )
    return Path(db.engine.url.database).resolve()


def _write_backup(output):
    database = _database_path()
    if not database.exists():
        raise click.ClickException("Database does not exist. Apply migrations first.")
    output = Path(output).resolve()
    if output.exists():
        raise click.ClickException(
            "The backup destination already exists. Choose a new filename."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    uploads = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    if output.is_relative_to(uploads):
        raise click.ClickException("Save backups outside the uploads directory.")
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / "database.sqlite3"
        source = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        manifest = {"format": 1, "created_at": utcnow().isoformat(), "files": {}}
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with (
            os.fdopen(descriptor, "wb") as handle,
            zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive,
        ):
            files = [(snapshot, "database.sqlite3")]
            if uploads.exists():
                files.extend(
                    (p, f"uploads/{p.relative_to(uploads).as_posix()}")
                    for p in uploads.rglob("*")
                    if p.is_file() and not p.is_symlink()
                )
            for path, name in files:
                archive.write(path, name)
                manifest["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    os.chmod(output, 0o600)
    return output


def register_commands(app):
    @app.cli.command("create-admin")
    @click.option("--email", prompt=True, help="Administrator email address.")
    @click.option("--name", default="Administrator", prompt=True)
    def create_admin(email, name):
        """Create an administrator; prompts securely for a unique password."""
        try:
            email = validate_email(
                email.strip(), check_deliverability=False
            ).normalized.lower()
        except EmailNotValidError as exc:
            raise click.ClickException(str(exc)) from exc
        if not name.strip() or len(name) > 120:
            raise click.ClickException("Name must contain 1–120 characters.")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("An account already exists for that email.")
        password = os.getenv("ADMIN_PASSWORD") or click.prompt(
            "Password (at least 12 characters)",
            hide_input=True,
            confirmation_prompt=True,
        )
        user = User(email=email, name=name.strip(), role="admin", active=True)
        try:
            user.set_password(password)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        db.session.add(user)
        db.session.commit()
        click.echo("Administrator created. Sign in using the credentials you supplied.")

    @app.cli.command("reset-password")
    @click.option("--email", required=True)
    def reset_password(email):
        """Reset an existing administrator’s password using a secure prompt."""
        from app.services.common import audit

        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            raise click.ClickException("Account not found.")
        password = os.getenv("ADMIN_PASSWORD") or click.prompt(
            "New password (at least 12 characters)",
            hide_input=True,
            confirmation_prompt=True,
        )
        try:
            user.set_password(password)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        audit(
            "reset_password",
            "User",
            user.id,
            "Password reset through the local administration command.",
        )
        db.session.commit()
        click.echo(
            "Password reset. Existing sessions lose access on their next request."
        )

    @app.cli.command("set-user-active")
    @click.option("--email", required=True)
    @click.option(
        "--active/--inactive", default=None, help="Activate or deactivate an account."
    )
    def set_user_active(email, active):
        """Control access while retaining historical ownership and audit records."""
        from app.services.common import audit

        if active is None:
            raise click.ClickException("Specify --active or --inactive.")
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            raise click.ClickException("Account not found.")
        if (
            not active
            and user.active
            and user.role == "admin"
            and User.query.filter_by(role="admin", active=True).count() <= 1
        ):
            raise click.ClickException(
                "Create or activate another administrator before disabling the last active administrator."
            )
        user.active = active
        audit(
            "activate_account" if active else "deactivate_account",
            "User",
            user.id,
            "Access changed through the local administration command.",
        )
        db.session.commit()
        click.echo(
            "Account activated."
            if active
            else "Account deactivated. Existing sessions lose access on their next request."
        )

    @app.cli.command("init-db")
    def init_db():
        """Create tables in development only. Use db upgrade for managed installs."""
        if current_app.config["APP_ENV"] != "development":
            raise click.ClickException("Use flask db upgrade outside development.")
        db.create_all()
        from app.services.document_service import seed_templates

        seed_templates()
        db.session.commit()
        click.echo("Development schema and document/email templates initialized.")

    @app.cli.command("seed-templates")
    def seed_templates_command():
        """Install missing document and email templates without replacing edits."""
        from app.services.document_service import seed_templates

        seed_templates()
        db.session.commit()
        click.echo("Document and email templates are ready.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Populate an empty development database with clearly fictional records."""
        if current_app.config["APP_ENV"] != "development":
            raise click.ClickException(
                "Demo data is allowed only with APP_ENV=development."
            )
        if ApplicationSetting.query.filter_by(key="demo_mode", value="true").first():
            click.echo("Demonstration data already exists; nothing changed.")
            return
        if any(
            db.session.scalar(db.select(db.func.count()).select_from(model))
            for model in (Client, Lead, Project)
        ):
            raise click.ClickException(
                "Demo seed requires an empty business database to prevent mixing real data."
            )
        administrator = User.query.filter_by(role="admin", active=True).first()
        if not administrator:
            raise click.ClickException(
                "Create your administrator with create-admin before seeding demonstration data."
            )
        _seed_demo(administrator)
        db.session.commit()
        click.echo(
            "Fictional demonstration workspace created. All business records are examples; email remains in test mode."
        )

    @app.cli.command("backup")
    @click.option(
        "--output",
        required=True,
        type=click.Path(path_type=Path),
        help="New ZIP file, stored outside uploads.",
    )
    def backup(output):
        """Back up SQLite consistently and include private uploads. Stop writers for files."""
        click.echo(f"Backup created: {_write_backup(output)}")

    @app.cli.command("restore")
    @click.argument("archive_path", type=click.Path(exists=True, path_type=Path))
    @click.option(
        "--yes",
        is_flag=True,
        help="Confirm web and scheduler are stopped, and replace current data.",
    )
    def restore(archive_path, yes):
        """Validate and restore a local backup after stopping web/scheduler processes."""
        if not yes:
            raise click.ClickException(
                "Stop the web server and scheduler, then pass --yes to replace data."
            )
        database = _database_path()
        uploads = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    names = archive.namelist()
                    if len(names) != len(set(names)) or len(names) > 50000:
                        raise ValueError("Duplicate or excessive archive entries.")
                    total = sum(item.file_size for item in archive.infolist())
                    if total > 1024 * 1024 * 1024:
                        raise ValueError("Archive exceeds the 1 GiB restoration limit.")
                    manifest = json.loads(archive.read("manifest.json"))
                    if manifest.get(
                        "format"
                    ) != 1 or "database.sqlite3" not in manifest.get("files", {}):
                        raise ValueError("Unsupported backup format.")
                    if set(names) != set(manifest["files"]) | {"manifest.json"}:
                        raise ValueError("Archive contents do not match the manifest.")
                    for name, expected_hash in manifest["files"].items():
                        parts = PurePosixPath(name)
                        if (
                            parts.is_absolute()
                            or ".." in parts.parts
                            or "\\" in name
                            or name not in {"database.sqlite3"}
                            and not name.startswith("uploads/")
                        ):
                            raise ValueError("Unsafe archive path.")
                        content = archive.read(name)
                        if hashlib.sha256(content).hexdigest() != expected_hash:
                            raise ValueError("Backup checksum validation failed.")
                        path = destination / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                source = destination / "database.sqlite3"
                with sqlite3.connect(source) as connection:
                    if (
                        connection.execute("PRAGMA integrity_check").fetchone()[0]
                        != "ok"
                    ):
                        raise ValueError("Database integrity check failed.")
                    if connection.execute("PRAGMA foreign_key_check").fetchall():
                        raise ValueError(
                            "Database contains invalid foreign key references."
                        )
                    tables = {
                        r[0]
                        for r in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    if not {"user", "client", "project"}.issubset(tables):
                        raise ValueError("The backup is not a Hanami database.")
            except (
                ValueError,
                KeyError,
                json.JSONDecodeError,
                zipfile.BadZipFile,
                sqlite3.DatabaseError,
            ) as exc:
                raise click.ClickException(f"Restore rejected: {exc}") from exc
            if database.exists():
                prior = (
                    Path(current_app.config["BACKUP_FOLDER"])
                    / f"before-restore-{utcnow():%Y%m%d%H%M%S%f}.zip"
                )
                _write_backup(prior)
                click.echo(f"Existing data preserved at {prior}")
            db.session.remove()
            db.engine.dispose()
            database.parent.mkdir(parents=True, exist_ok=True)
            replacement = database.with_name(database.name + ".restore")
            shutil.copyfile(source, replacement)
            os.chmod(replacement, 0o600)
            os.replace(replacement, database)
            for suffix in ("-wal", "-shm"):
                Path(str(database) + suffix).unlink(missing_ok=True)
            if uploads.exists():
                shutil.rmtree(uploads)
            shutil.copytree(destination / "uploads", uploads) if (
                destination / "uploads"
            ).exists() else uploads.mkdir(parents=True)
            click.echo(
                "Database and uploads restored. Apply any newer migrations before restarting services."
            )

    @app.cli.command("anonymize-client")
    @click.argument("client_id", type=int)
    @click.option(
        "--yes",
        is_flag=True,
        help="Confirm removal of the archived client’s current contact details.",
    )
    def anonymize_client(client_id, yes):
        """Clear aged archived contact profiles; financial and historical records remain."""
        from app.models import Contact, Invoice
        from app.services.common import audit, setting

        if not yes:
            raise click.ClickException(
                "This removes contact profile data. Take a backup and pass --yes to confirm."
            )
        client = db.session.get(Client, client_id)
        if not client:
            raise click.ClickException("Client not found.")
        if client.status != "archived":
            raise click.ClickException("Only archived clients can be anonymized.")
        try:
            retention_days = int(setting("retention_days", "365"))
            if retention_days < 30:
                raise ValueError
        except ValueError as exc:
            raise click.ClickException(
                "Configure retention_days as an integer of at least 30 days."
            ) from exc
        if client.updated_at > utcnow() - timedelta(days=retention_days):
            raise click.ClickException(
                f"The archived profile must remain unchanged for {retention_days} days before anonymization."
            )
        if any(
            project.status not in {"completed", "canceled", "cancelled", "archived"}
            for project in client.projects
        ):
            raise click.ClickException(
                "Resolve active projects before anonymizing a client."
            )
        if any(
            invoice.status != "void" and invoice.balance > 0
            for invoice in Invoice.query.filter_by(client_id=client.id).all()
        ):
            raise click.ClickException(
                "Resolve outstanding invoices before anonymizing a client."
            )
        client.name = f"Anonymized client {client.id}"
        for field in (
            "business_name",
            "email",
            "phone",
            "website",
            "industry",
            "location",
            "notes",
        ):
            setattr(client, field, "")
        for contact in Contact.query.filter_by(client_id=client.id).all():
            contact.name, contact.email, contact.phone, contact.role = (
                "Anonymized contact",
                "",
                "",
                "",
            )
        for lead in Lead.query.filter_by(client_id=client.id).all():
            lead.name = "Anonymized lead"
            for field in (
                "business_name",
                "email",
                "phone",
                "website",
                "industry",
                "location",
                "notes",
            ):
                setattr(lead, field, "")
        audit(
            "anonymize_profile",
            "Client",
            client.id,
            f"Archived contact profile anonymized after {retention_days} days. Historical records retained.",
        )
        db.session.commit()
        click.echo(
            "Contact profiles anonymized. Invoices, approvals, documents, emails, logs and backups still retain historical data; review their retention separately."
        )

    @app.cli.command("export-data")
    @click.option("--output", required=True, type=click.Path(path_type=Path))
    def export_data(output):
        """Export portable business JSON, excluding users and configuration secrets."""
        if output.exists():
            raise click.ClickException("The destination already exists.")
        records = {}
        for table in sorted(db.metadata.tables.values(), key=lambda item: item.name):
            if table.name in {"user", "application_setting"}:
                continue
            records[table.name] = [
                dict(row) for row in db.session.execute(db.select(table)).mappings()
            ]
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as target:
            json.dump(
                {"format": 1, "exported_at": utcnow().isoformat(), "records": records},
                target,
                indent=2,
                default=str,
            )
        click.echo(
            f"Business data exported: {output}. Store this private client data securely."
        )


def _seed_demo(administrator):
    from app.models import (
        Task,
        ScopeItem,
        ProjectMilestone,
        Approval,
        Notification,
        EmailDraft,
        BugReport,
        MaintenanceAgreement,
        Expense,
        Proposal,
        Inquiry,
        ActivityLog,
    )
    from app.services.document_service import seed_templates, generate_document
    from app.services.lifecycle_service import create_project
    from app.services.invoice_service import (
        calculate_proposal,
        accept_proposal,
        create_contract,
        execute_contract,
        create_invoice,
        issue_invoice,
        record_payment,
        verify_payment,
        reference,
    )

    seed_templates()
    now = utcnow()
    evidence = "DEMONSTRATION ONLY — fictional client confirmation for exploring the workspace."
    db.session.add(ApplicationSetting(key="demo_mode", value="true"))
    db.session.add(ApplicationSetting(key="email_test_mode", value="true"))
    clients = []
    for name, business, industry in [
        ("Luna Reyes", "Luna Coffee House", "Food & beverage"),
        ("Maya Santos", "Bloom & Stem", "Retail"),
        ("Nico Cruz", "Northline Studio", "Architecture"),
    ]:
        client = Client(
            name=name,
            business_name=business,
            email=f"{name.split()[0].lower()}@example.test",
            industry=industry,
            location="Metro Manila, Philippines",
            notes="DEMONSTRATION DATA — fictional business.",
        )
        db.session.add(client)
        clients.append(client)
    db.session.flush()
    for index, (name, business, status, source) in enumerate(
        [
            ("Aria Dela Cruz", "Greenhouse Wellness", "qualified", "Referral"),
            ("Leo Flores", "Orbit Cycling", "new", "Website"),
            ("Sofia Lim", "The Sunday Table", "awaiting_response", "Social media"),
            ("Kai Navarro", "Coastline Supply", "consultation_scheduled", "Referral"),
        ]
    ):
        db.session.add(
            Lead(
                name=name,
                business_name=business,
                email=f"demo.lead{index}@example.test",
                status=status,
                source=source,
                budget=Decimal("25000") + index * 5000,
                follow_up_at=now + timedelta(days=index - 1),
                notes="DEMONSTRATION DATA — fictional lead.",
            )
        )
    projects = []
    for index, (client, title, stage, value) in enumerate(
        zip(
            clients,
            [
                "Luna Coffee · Business Website",
                "Bloom & Stem · Online Store",
                "Northline · Portfolio Website",
            ],
            [8, 4, 10],
            [15000, 42000, 28000],
        )
    ):
        project = create_project(
            client,
            title,
            "DEMONSTRATION DATA — an example website project with fictional approvals.",
        )
        project.contract_value = Decimal(value)
        project.deadline = now + timedelta(days=[18, 35, 9][index])
        project.current_stage = stage
        db.session.flush()
        for phase in project.stages:
            phase.status = (
                "completed"
                if phase.number < stage
                else "in_progress"
                if phase.number == stage
                else "pending"
            )
            phase.completed_at = (
                now - timedelta(days=stage - phase.number)
                if phase.number < stage
                else None
            )
            if phase.number < stage:
                phase.data = {"demo": True, "summary": evidence}
        for requirement in project.requirements:
            requirement.completed = requirement.stage_number < stage
        projects.append(project)
        db.session.add(
            ProjectMilestone(
                project_id=project.id,
                title=["Design review", "Scope approval", "User acceptance testing"][
                    index
                ],
                due_at=now + timedelta(days=index + 2),
            )
        )
        db.session.add(
            ActivityLog(
                client_id=client.id,
                project_id=project.id,
                action="demo_created",
                description=f"Demonstration project created: {title}",
            )
        )
    luna = projects[0]
    for name, hours in [
        ("Homepage", 6),
        ("Menu", 5),
        ("About page", 3),
        ("Contact page", 3),
        ("Contact form", 4),
        ("Maps integration", 2),
        ("Mobile responsiveness", 7),
    ]:
        db.session.add(
            ScopeItem(
                project_id=luna.id,
                name=name,
                hours=hours,
                rate=500,
                acceptance_criteria="Page is accessible and works at mobile and desktop widths.",
                status="approved",
            )
        )
    db.session.flush()
    proposal = Proposal(
        reference=reference("PROP"),
        project_id=luna.id,
        title="Luna Coffee House website proposal",
        status="draft",
        currency="PHP",
        overview="A welcoming digital home for a neighborhood coffee house.",
        deliverables="Homepage, menu, about, contact form, maps and responsive layouts.",
        terms="40% deposit, 30% design approval, 30% final acceptance.",
        timeline="Six weeks after complete content delivery.",
    )
    calculate_proposal(
        proposal,
        [
            dict(
                description="Business website design and development",
                quantity=1,
                unit_price=15000,
            )
        ],
    )
    db.session.add(proposal)
    db.session.flush()
    proposal.status = "approved"
    db.session.flush()
    accept_proposal(proposal, clients[0].name, evidence, administrator.id)
    db.session.flush()
    contract = create_contract(proposal)
    execute_contract(contract, clients[0].name, evidence, administrator.id)
    db.session.flush()
    for index, amount in enumerate([6000, 4500, 4500]):
        invoice = create_invoice(
            luna,
            [
                dict(
                    description=[
                        "40% project deposit",
                        "30% design milestone",
                        "30% final acceptance",
                    ][index],
                    quantity=1,
                    unit_price=amount,
                )
            ],
            kind=["deposit", "milestone", "final"][index],
            due_at=(now + timedelta(days=[-7, 7, 25][index])).date(),
            contract_id=contract.id,
        )
        issue_invoice(invoice)
        if index == 0:
            payment = record_payment(
                invoice, amount, "Bank transfer (demo)", "DEMO-LUNA-DEPOSIT"
            )
            db.session.flush()
            verify_payment(payment, evidence, administrator.id)
    db.session.add(
        Expense(
            project_id=luna.id,
            description="Stock photography license (demo)",
            amount=500,
            currency="PHP",
            category="Assets",
        )
    )
    for index, title in enumerate(
        [
            "Review homepage design with Luna",
            "Collect product photography",
            "Confirm mobile navigation behavior",
            "Prepare the weekly progress update",
            "Review accessibility test results",
        ]
    ):
        project = projects[index % len(projects)]
        db.session.add(
            Task(
                project_id=project.id,
                client_id=project.client_id,
                title=title,
                status="in_progress" if index == 0 else "todo",
                priority="high" if index in (0, 2) else "medium",
                due_at=now + timedelta(days=index - 1),
                assigned_user_id=administrator.id,
                estimated_hours=2,
            )
        )
    db.session.add(
        Inquiry(
            client_id=clients[0].id,
            project_id=luna.id,
            website_type="Business website",
            business_description="DEMO: Neighborhood cafe serving specialty coffee.",
            features="Menu, contact form, maps",
            budget=15000,
            status="reviewed",
            answers={
                "business_name": "Luna Coffee House",
                "purpose": "Help local guests find us",
            },
        )
    )
    db.session.add(
        EmailDraft(
            client_id=clients[0].id,
            project_id=luna.id,
            recipient=clients[0].email,
            subject="Your first design is ready for review",
            body="Hello Luna,\n\nYour homepage design is ready for review. Please share your feedback.\n\nDEMONSTRATION ONLY — this draft has not been sent.",
            status="draft",
        )
    )
    db.session.add(
        EmailDraft(
            client_id=clients[1].id,
            project_id=projects[1].id,
            recipient=clients[1].email,
            subject="A few details for your project scope",
            body="Hello Maya,\n\nPlease review the proposed store features and confirm your priorities.\n\nDEMONSTRATION ONLY.",
            status="draft",
        )
    )
    generate_document(
        luna, "scope_of_work", title="Luna Coffee · Scope of Work (demonstration)"
    )
    db.session.add(
        BugReport(
            project_id=projects[2].id,
            title="Mobile gallery images need descriptive alternatives",
            description="DEMONSTRATION: add useful alt text to the project gallery.",
            severity="medium",
            status="open",
        )
    )
    db.session.add(
        MaintenanceAgreement(
            project_id=projects[2].id,
            client_id=clients[2].id,
            name="Northline care plan (demonstration)",
            website="https://example.test",
            monthly_fee=1500,
            currency="PHP",
            start_date=now.date(),
            renewal_date=(now + timedelta(days=30)).date(),
            covered_services="Monthly backups, security updates and uptime review.",
            status="draft",
        )
    )
    db.session.add(
        Approval(
            project_id=luna.id,
            stage_number=4,
            kind="scope",
            decision="approved",
            person=clients[0].name,
            evidence=evidence,
            actor_id=administrator.id,
        )
    )
    db.session.add(
        Notification(
            title="Welcome to your demonstration workspace",
            body="Explore the fictional projects and records. Emails stay in test mode.",
            project_id=luna.id,
        )
    )

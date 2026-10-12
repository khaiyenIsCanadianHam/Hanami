"""Literal-only templates and immutable document versions. Never execute template code."""

import hashlib
import io
import re
import uuid
from html import escape
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.base import utcnow
from app.models.communications import (
    Document,
    DocumentTemplate,
    EmailTemplate,
    FileAttachment,
)
from app.services.common import log_activity, setting

VARIABLES = {
    "client_name",
    "business_name",
    "client_email",
    "project_name",
    "project_id",
    "project_status",
    "project_description",
    "contract_value",
    "currency",
    "deadline",
    "invoice_number",
    "invoice_amount",
    "invoice_due_date",
    "milestone_name",
    "developer_name",
    "business_email",
    "company_name",
    "scope_items",
    "milestones",
    "stage",
    "today",
    "revision_allowance",
    "repository_url",
    "staging_url",
}
PLACEHOLDER = re.compile(r"{{\s*([a-z_]+)\s*}}")


def validate_template(value):
    """Accept only known literal placeholders; reject all expression/control syntax."""
    if len(value) > 100_000:
        raise ValueError("Template is too large (maximum 100,000 characters).")
    unknown = set(PLACEHOLDER.findall(value)) - VARIABLES
    remainder = PLACEHOLDER.sub("", value)
    if unknown:
        raise ValueError("Unknown template variables: " + ", ".join(sorted(unknown)))
    if any(marker in remainder for marker in ("{{", "}}", "{%", "%}", "{#", "#}")):
        raise ValueError(
            "Use only supported {{variable}} placeholders; expressions are not allowed."
        )


def render_literal(value, context, html=False):
    validate_template(value)

    def substitute(match):
        key = match.group(1)
        rendered = str(
            context.get(key) if context.get(key) is not None else f"[missing:{key}]"
        )
        return escape(rendered) if html else rendered

    return PLACEHOLDER.sub(substitute, value)


def project_context(project=None):
    values = {
        "today": utcnow().date().isoformat(),
        "developer_name": setting("developer_name", "Your developer"),
        "company_name": setting("company_name", "Hanami"),
        "business_email": setting("business_email", ""),
    }
    if project is None:
        return values
    from app.models.core import Client, ScopeItem, ProjectMilestone

    client = db.session.get(Client, project.client_id)
    values.update(
        client_name=client.name,
        business_name=client.business_name or client.name,
        client_email=client.email or "",
        project_name=project.title,
        project_id=project.reference,
        project_status=project.status,
        project_description=project.description or "",
        contract_value=str(project.contract_value or "0.00"),
        currency=project.currency,
        deadline=str(project.deadline or "To be agreed"),
        stage=str(project.current_stage),
        revision_allowance=str(project.revision_allowance),
        repository_url=project.repository_url or "Not recorded",
        staging_url=project.staging_url or "Not recorded",
    )
    values["scope_items"] = (
        "\n".join(
            f"- {'Included' if row.included else 'Excluded'}: {row.name}; {row.description or ''}; "
            f"Acceptance: {row.acceptance_criteria or 'Review required'}"
            for row in ScopeItem.query.filter_by(project_id=project.id).order_by(
                ScopeItem.id
            )
        )
        or "Scope needs review."
    )
    values["milestones"] = (
        "\n".join(
            f"- {row.title}: {row.due_at or 'Date to be agreed'}"
            for row in ProjectMilestone.query.filter_by(project_id=project.id).order_by(
                ProjectMilestone.id
            )
        )
        or "Milestones need review."
    )
    return values


DOCUMENT_SPECS = [
    (
        "lead_inquiry",
        "Lead inquiry form",
        "Sales",
        "Contact: {{client_name}}\nBusiness: {{business_name}}\nObjectives:\nBudget:\nPreferred launch date:",
    ),
    (
        "discovery_questionnaire",
        "Discovery questionnaire",
        "Discovery",
        "1. What does your business offer?\n2. Who is your audience?\n3. What problem will the website solve?\n4. Required pages/features?\n5. Existing website?\n6. Accounts, payments, or bookings?\n7. Brand and content assets?\n8. Domain and hosting?\n9. Budget and launch constraints?\n10. Privacy and maintenance needs?",
    ),
    (
        "consultation_notes",
        "Consultation notes",
        "Discovery",
        "Attendees:\nObjectives:\nDecisions:\nUnresolved questions:\nAction owner and due date:",
    ),
    (
        "requirements",
        "Requirements document",
        "Discovery",
        "{{project_description}}\n\n{{scope_items}}\n\nSecurity and privacy requirements:\nIntegration requirements:\nAdministrator review:",
    ),
    (
        "scope_of_work",
        "Scope of Work",
        "Planning",
        "{{project_description}}\n\n{{scope_items}}\n\nClient responsibilities:\nAssumptions and constraints:\nRevision allowance: {{revision_allowance}}\nAcceptance evidence:",
    ),
    (
        "project_timeline",
        "Project timeline",
        "Planning",
        "{{milestones}}\n\nTarget deadline: {{deadline}}\nDates remain subject to recorded approval.",
    ),
    (
        "milestone_plan",
        "Milestone plan",
        "Planning",
        "{{milestones}}\n\nDependencies:\nAcceptance owner:",
    ),
    (
        "feature_specification",
        "Feature specification",
        "Planning",
        "{{scope_items}}\n\nAccessibility:\nSecurity:\nValidation and test evidence:",
    ),
    (
        "proposal",
        "Project proposal",
        "Commercial",
        "{{project_description}}\n\n{{scope_items}}\n\n{{milestones}}\n\nContract value recorded: {{currency}} {{contract_value}}\nPricing, payment schedule, exclusions and expiration require review.\nClient acceptance evidence:",
    ),
    (
        "quotation",
        "Quotation",
        "Commercial",
        "{{scope_items}}\n\nRecorded contract value: {{currency}} {{contract_value}}\nUse the proposal builder for itemized, verified totals.\nValidity and payment schedule:",
    ),
    (
        "development_agreement",
        "Development agreement",
        "Commercial",
        "DRAFT — REQUIRES PROFESSIONAL REVIEW\nParties: {{business_name}} and {{company_name}}\n{{scope_items}}\n\nPayment terms:\nRevisions and change requests:\nIntellectual property:\nConfidentiality:\nCancellation and termination:\nWarranty and exclusions:\nDispute handling:\nSignatures and dates:",
    ),
    (
        "invoice",
        "Invoice cover sheet",
        "Commercial",
        "Invoice: {{invoice_number}}\nAmount: {{invoice_amount}}\nDue: {{invoice_due_date}}\nGenerate the authoritative itemized invoice in Finance.\nPayment instructions:",
    ),
    (
        "payment_reminder",
        "Payment reminder",
        "Commercial",
        "Invoice {{invoice_number}}\nOutstanding: {{invoice_amount}}\nDue: {{invoice_due_date}}\nPlease provide payment reference for verification.",
    ),
    (
        "receipt",
        "Payment acknowledgment",
        "Commercial",
        "Invoice {{invoice_number}}\nAmount: {{invoice_amount}}\nVerified payment reference:\nVerification date:\nThis draft does not itself verify payment or constitute a tax receipt.",
    ),
    (
        "design_feedback",
        "Design feedback form",
        "Design",
        "Design version:\nPage/component:\nFeedback:\nAcceptance criteria:\nDecision and evidence:",
    ),
    (
        "design_approval",
        "Design approval",
        "Design",
        "Version reviewed:\nApproved pages/components:\nConditions:\nClient decision, name and date:\nEvidence reference:",
    ),
    (
        "weekly_progress",
        "Weekly progress report",
        "Development",
        "Current stage: {{stage}}\nCompleted work:\nUpcoming work:\nBlockers and decisions:\n{{milestones}}",
    ),
    (
        "change_request",
        "Change request",
        "Development",
        "Requested change:\nBusiness reason:\nScope impact:\nCost impact:\nSchedule impact:\nClient decision and approval evidence:",
    ),
    (
        "bug_report",
        "Bug report",
        "Testing",
        "Environment:\nSteps to reproduce:\nExpected result:\nActual result:\nSeverity:\nResolution and retest evidence:",
    ),
    (
        "qa_report",
        "QA report",
        "Testing",
        "Functional coverage:\nResponsive/accessibility checks:\nSecurity checks:\nOpen defects:\nExecuted test evidence:\nReviewer and date:",
    ),
    (
        "uat_checklist",
        "UAT checklist",
        "Testing",
        "{{scope_items}}\n\nClient test results:\nUnresolved issues:\nAcceptance evidence:",
    ),
    (
        "acceptance_form",
        "Acceptance form",
        "Delivery",
        "Deliverables reviewed:\n{{scope_items}}\n\nConditions and exceptions:\nClient name, decision and date:\nEvidence reference:",
    ),
    (
        "launch_checklist",
        "Launch checklist",
        "Delivery",
        "[ ] Written client approval\n[ ] Verified payment\n[ ] Backup and rollback plan\n[ ] DNS/SSL reviewed\n[ ] Forms tested\n[ ] Analytics/privacy reviewed\n[ ] Production smoke test\nEvidence:",
    ),
    (
        "handover",
        "Handover document",
        "Delivery",
        "{{project_description}}\n\nRepository: {{repository_url}}\nStaging: {{staging_url}}\n\nOwnership and secure access transfer:\nTraining completed:\nBackup/restore procedure:\nWarranty terms:\nMaintenance options:\nClient acknowledgment:\nNever include passwords in this document.",
    ),
    (
        "completion_report",
        "Project completion report",
        "Delivery",
        "{{scope_items}}\n\n{{milestones}}\n\nAcceptance evidence:\nLaunch evidence:\nHandover evidence:\nLessons learned:",
    ),
    (
        "maintenance_agreement",
        "Maintenance agreement",
        "Support",
        "DRAFT — REQUIRES PROFESSIONAL REVIEW\nIncluded services:\nFrequency:\nResponse targets:\nExclusions:\nPrice and renewal:\nCancellation:\nApproval evidence:",
    ),
    (
        "support_ticket",
        "Support ticket",
        "Support",
        "Reported issue:\nPriority:\nEnvironment:\nInvestigation:\nResolution:\nClient confirmation:",
    ),
    (
        "maintenance_report",
        "Maintenance report",
        "Support",
        "Reporting period:\nVerified activities and execution evidence:\nBackups tested:\nSecurity updates:\nOpen issues:\nRecommendations:",
    ),
    (
        "renewal_reminder",
        "Renewal reminder",
        "Support",
        "Service/domain/hosting:\nRenewal date:\nAmount and instructions:\nApproval required before renewal.",
    ),
]

EMAIL_SPECS = [
    (
        "introduction",
        "Initial introduction",
        "Sales",
        "Website services for {{business_name}}",
        "Hello {{client_name}},\n\nThank you for connecting. I would be happy to learn about your website goals. Please share your priorities and preferred time for a conversation.",
    ),
    (
        "inquiry_acknowledgment",
        "Inquiry acknowledgment",
        "Inquiry",
        "Your website inquiry",
        "Hello {{client_name}},\n\nThank you for your inquiry. Please share your business objectives, required pages/features, budget range and desired launch date. We will review feasibility together before confirming scope, cost or dates.",
    ),
    (
        "missing_information",
        "Missing information request",
        "Inquiry",
        "A few details for {{project_name}}",
        "Hello {{client_name}},\n\nWe need additional information before proceeding. Please review the attached questionnaire and confirm the outstanding requirements.",
    ),
    (
        "consultation_invitation",
        "Consultation invitation",
        "Discovery",
        "Discovery consultation for {{project_name}}",
        "Hello {{client_name}},\n\nPlease let us know a suitable time to discuss your objectives, audience, features, content, budget and timeline.",
    ),
    (
        "discovery_follow_up",
        "Discovery follow-up",
        "Discovery",
        "Discovery summary: {{project_name}}",
        "Hello {{client_name}},\n\nThank you for the consultation. Please review the discovery summary and confirm our understanding of your requirements.",
    ),
    (
        "scope_review",
        "Scope review",
        "Planning",
        "Scope review: {{project_name}}",
        "Hello {{client_name}},\n\nPlease review the proposed scope and acceptance criteria. We will proceed after your explicit approval.",
    ),
    (
        "proposal_submission",
        "Proposal submission",
        "Proposal",
        "Proposal: {{project_name}}",
        "Hello {{client_name}},\n\nPlease review the proposal, pricing, payment schedule and assumptions. Reply with questions or your recorded acceptance.",
    ),
    (
        "follow_up",
        "Proposal or inquiry follow-up",
        "Sales",
        "Following up on {{project_name}}",
        "Hello {{client_name}},\n\nPlease let us know if you have any questions or would prefer that we close this inquiry.",
    ),
    (
        "polite_decline",
        "Polite decline",
        "Sales",
        "Your website inquiry",
        "Hello {{client_name}},\n\nThank you for considering our services. We are unable to take on this engagement at present and wish you success with your project.",
    ),
    (
        "contract_deposit",
        "Contract and deposit",
        "Contract",
        "Agreement and deposit: {{project_name}}",
        "Hello {{client_name}},\n\nPlease review the draft agreement and initial invoice. Work begins after the required agreement and verified payment are recorded.",
    ),
    (
        "onboarding",
        "Client onboarding",
        "Onboarding",
        "Welcome to {{project_name}}",
        "Hello {{client_name}},\n\nPlease provide your brand assets, content, ownership contacts and required access through an agreed secure method. Do not send passwords by email.",
    ),
    (
        "design_review",
        "Design approval request",
        "Design",
        "Design review: {{project_name}}",
        "Hello {{client_name}},\n\nThe design is ready for your review. Please record feedback or explicit approval for the identified version.",
    ),
    (
        "progress_report",
        "Project progress",
        "Development",
        "Progress update: {{project_name}}",
        "Hello {{client_name}},\n\nCurrent project status: {{project_status}}. Please review the attached progress report for completed work, next steps and outstanding decisions.",
    ),
    (
        "testing_invitation",
        "User acceptance testing",
        "Testing",
        "Testing: {{project_name}}",
        "Hello {{client_name}},\n\nPlease complete the acceptance checklist and report any issues with steps to reproduce. We will record your final decision separately.",
    ),
    (
        "final_acceptance",
        "Final acceptance request",
        "Acceptance",
        "Final acceptance: {{project_name}}",
        "Hello {{client_name}},\n\nPlease review the completed deliverables and record final acceptance. The final invoice and verified payment are required before launch.",
    ),
    (
        "payment_reminder",
        "Payment reminder",
        "Finance",
        "Reminder: invoice {{invoice_number}}",
        "Hello {{client_name}},\n\nInvoice {{invoice_number}} has an outstanding amount of {{invoice_amount}} and is due {{invoice_due_date}}. If you have paid, please provide the payment reference for verification.",
    ),
    (
        "launch_confirmation",
        "Launch confirmation",
        "Launch",
        "Launch update: {{project_name}}",
        "Hello {{client_name}},\n\nPlease review the recorded launch results and report any issues. Your approval and launch evidence are retained in the project record.",
    ),
    (
        "handover",
        "Website handover",
        "Handover",
        "Handover: {{project_name}}",
        "Hello {{client_name}},\n\nPlease review the handover documentation, training arrangements, warranty and support options. Access credentials will be transferred securely.",
    ),
    (
        "maintenance_report",
        "Maintenance report",
        "Support",
        "Maintenance: {{project_name}}",
        "Hello {{client_name}},\n\nPlease review the maintenance report for verified work, open issues and recommendations.",
    ),
    (
        "renewal_reminder",
        "Renewal reminder",
        "Support",
        "Upcoming renewal: {{project_name}}",
        "Hello {{client_name}},\n\nA service renewal is approaching. Please review the details and confirm your preferred next step before any purchase is made.",
    ),
]


def seed_templates():
    for key, name, category, body in DOCUMENT_SPECS:
        if not DocumentTemplate.query.filter_by(key=key).first():
            db.session.add(
                DocumentTemplate(
                    key=key,
                    name=name,
                    category=category,
                    body=f"# {name}\n\nClient: {{{{client_name}}}}\nProject: {{{{project_name}}}}\nPrepared: {{{{today}}}}\n\n{body}\n",
                )
            )
    for key, name, category, subject, body in EMAIL_SPECS:
        if not EmailTemplate.query.filter_by(key=key).first():
            db.session.add(
                EmailTemplate(
                    key=key,
                    name=name,
                    category=category,
                    subject=subject,
                    body=body + "\n\nKind regards,\n{{developer_name}}",
                )
            )


def generate_document(project, template_key, title=None, context=None):
    template = (
        DocumentTemplate.query.filter_by(key=template_key, archived=False)
        .order_by(DocumentTemplate.version.desc())
        .first()
    )
    if template is None:
        raise ValueError("Choose an active document template.")
    values = project_context(project)
    values.update(context or {})
    document = Document(
        project_id=project.id,
        client_id=project.client_id,
        template_id=template.id,
        title=title or f"{template.name} — {project.title}",
        body=render_literal(template.body, values),
    )
    db.session.add(document)
    log_activity(
        "document.generated",
        f"Generated {template.name} draft.",
        project_id=project.id,
        client_id=project.client_id,
    )
    return document


def export_pdf(document):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    output = io.BytesIO()
    styles = getSampleStyleSheet()
    font_file = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if font_file.is_file():
        if "CRMUnicode" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("CRMUnicode", str(font_file)))
        for style in styles.byName.values():
            style.fontName = "CRMUnicode"
    styles["BodyText"].alignment = TA_LEFT
    styles["BodyText"].wordWrap = "CJK"
    story = [
        Paragraph(escape(document.title), styles["Title"]),
        Paragraph(
            f"{escape(document.status.upper())} · Version {document.version}",
            styles["Normal"],
        ),
        Spacer(1, 18),
    ]
    for line in document.body.splitlines():
        if not line.strip():
            story.append(Spacer(1, 8))
        else:
            style = styles["Heading2"] if line.startswith("#") else styles["BodyText"]
            story.append(
                Paragraph(
                    escape(line.lstrip("# ") if line.startswith("#") else line), style
                )
            )
    SimpleDocTemplate(
        output, title=document.title, author=setting("company_name", "Hanami")
    ).build(story)
    output.seek(0)
    return output


def upload_root():
    root = Path(
        current_app.config.get("UPLOAD_FOLDER")
        or Path(current_app.instance_path) / "uploads"
    ).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def attachment_path(attachment):
    root = upload_root()
    path = (root / attachment.stored_name).resolve()
    if path.parent != root:
        raise ValueError("Invalid stored file path.")
    return path


def save_attachment(file, project=None, uploaded_by=None):
    name = secure_filename(file.filename or "")
    if not name or len(name) > 240:
        raise ValueError("Provide a valid filename of at most 240 characters.")
    extension = Path(name).suffix.lower()
    limit = min(
        current_app.config.get("MAX_CONTENT_LENGTH") or 10 * 1024 * 1024,
        10 * 1024 * 1024,
    )
    data = file.stream.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("Files must be nonempty and at most 10 MB.")
    content_type = None
    if extension == ".pdf" and data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]:
        content_type = "application/pdf"
    elif extension == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        content_type = "image/png"
    elif (
        extension in {".jpg", ".jpeg"}
        and data.startswith(b"\xff\xd8\xff")
        and data.endswith(b"\xff\xd9")
    ):
        content_type = "image/jpeg"
    elif extension in {".txt", ".md", ".csv"}:
        try:
            decoded = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text files must use UTF-8 encoding.") from exc
        if any(ord(char) < 32 and char not in "\n\r\t" for char in decoded):
            raise ValueError("Text files cannot contain binary control characters.")
        content_type = "text/plain"
    if content_type is None:
        raise ValueError(
            "Only verified PDF, PNG, JPEG, UTF-8 TXT, Markdown and CSV files are allowed."
        )
    stored_name = uuid.uuid4().hex + extension
    path = upload_root() / stored_name
    with path.open("xb") as target:
        target.write(data)
    path.chmod(0o600)
    attachment = FileAttachment(
        original_name=name,
        stored_name=stored_name,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        uploaded_by=uploaded_by,
        project_id=project.id if project else None,
        client_id=project.client_id if project else None,
    )
    db.session.add(attachment)
    return attachment

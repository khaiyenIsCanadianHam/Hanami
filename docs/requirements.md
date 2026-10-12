# MASTER DEVELOPMENT PROMPT
# WebDev CRM — Complete Website Development Client Lifecycle Management System

## 1. ROLE AND OBJECTIVE

Act as a senior full-stack software engineer, software architect, UI/UX designer, database designer, quality assurance engineer, and business workflow automation specialist.

Your task is to develop a complete, modular, maintainable, and secure **Website Development Client Management System**, hereafter referred to as **WebDev CRM**.

This application will be used by a freelance website developer or small website development agency to manage clients throughout their entire lifecycle, from discovering a potential client to delivering the finished website, collecting payments, and maintaining a long-term professional relationship.

The application must automate as many repetitive administrative tasks as reasonably possible without removing essential human supervision, contractual approval, financial verification, or security checks.

The system must operate as a locally hosted Flask web application accessible through a modern browser.

Use a clean, modern, responsive interface with comprehensive dashboards, forms, tables, visual reports, timelines, calendars, document previews, and workflow controls.

The final result must be an operational business management application, not merely a collection of disconnected forms.

---

# 2. REQUIRED TECHNOLOGY STACK

Use the following technologies.

### Backend
- Python 3.12 or a compatible supported Python version
- Flask
- Flask-SQLAlchemy
- Flask-Migrate
- Flask-Login
- Flask-WTF for form validation and CSRF protection
- Werkzeug password hashing
- SQLite database
- yagmail for Gmail-compatible SMTP email sending
- APScheduler for local scheduled automation
- Jinja2 template rendering
- WeasyPrint or another suitable PDF generation library
- python-dotenv for environment variables

### Frontend
- HTML5
- CSS3
- Vanilla JavaScript (ES6+)
- Fetch API for asynchronous requests
- Chart.js for charts and analytics
- FullCalendar or a comparable calendar library for project scheduling
- Responsive layouts with CSS Grid and Flexbox
- Lucide icons or an equivalent consistent icon set

### Architecture rules
1. Flask must control backend business logic and serve the GUI.
2. SQLite must store persistent business data.
3. Use SQLAlchemy ORM models instead of manually building SQL strings throughout the application.
4. Organize the project using Flask Blueprints.
5. Use Jinja2 templates for reusable page layouts.
6. Use modular CSS and JavaScript files.
7. Avoid unnecessary frontend frameworks.
8. Protect administrative endpoints with authentication and authorization.
9. Do not hardcode email credentials, secret keys, or other confidential information.
10. Design the database and application services so that SQLite can eventually be replaced with PostgreSQL.
11. Store dates internally in UTC and display them using the configured business timezone, defaulting to Asia/Manila.
12. Use Decimal values for financial calculations rather than floating-point arithmetic.
13. Implement SQLite foreign keys, migrations, transaction management, and appropriate indexes.
14. Use a persistent scheduler that avoids duplicate task execution and records job status.
15. Support a single-administrator deployment initially, with data structures that allow future team accounts.

---

# 3. COMPLETE CLIENT LIFECYCLE

Implement the following 14 stages as an integrated project workflow:

1. Client Acquisition
2. Initial Inquiry
3. Discovery and Consultation
4. Project Scope and Planning
5. Proposal and Quotation
6. Contract and Deposit
7. Client Onboarding
8. Website Design and Approval
9. Website Development
10. Testing and Revisions
11. Final Acceptance and Payment
12. Deployment and Launch
13. Website Handover and Training
14. Maintenance and Support

Each stage must have:

- A dedicated interface.
- Its own checklist.
- Required and optional fields.
- Relevant document templates.
- Email templates.
- Automation triggers.
- Tasks and reminders.
- Progress indicators.
- Submission validation.
- Approval requirements.
- Activity history.
- Associated files and notes.
- Defined completion conditions.
- The ability to return to an earlier stage when necessary.
- Clear separation between draft, submitted, approved, rejected, and completed statuses.

Do not assume the project can only move forward in a straight line.

Projects may pause, require revisions, be canceled, or return to earlier stages.

Important milestones must require deliberate user or client confirmation.

---

# 4. MODULE 1 — CLIENT ACQUISITION

Develop a lead management interface.

A lead represents a potential client who has not yet become a confirmed paying customer.

### Features

Create and manage leads with the following information:

- Lead ID
- Contact person
- Business name
- Email address
- Phone number
- Website, if existing
- Business industry
- Business location
- Lead source
- Requested service
- Estimated budget
- Desired project date
- Notes
- Lead status
- Date created
- Date last contacted
- Next follow-up date

### Lead statuses

- New
- Contacted
- Awaiting Response
- Qualified
- Consultation Scheduled
- Proposal Requested
- Converted
- Lost
- Archived

### Lead management dashboard

Include:

- Total active leads
- New leads this month
- Qualified leads
- Converted leads
- Conversion rate
- Leads requiring follow-up
- Lead source breakdown
- Lead pipeline visualization

### Automations

When a lead is created:

1. Generate a unique lead identifier.
2. Create an activity record.
3. Schedule an internal qualification task.
4. Prepare an initial introduction email using a template.
5. Allow the administrator to review and approve the email before sending.

If a lead is awaiting a response, generate a follow-up suggestion according to configurable business rules.

Do not automatically send repeated sales messages without the required consent or lawful basis.

Provide manual email sending as the default behavior.

### Templates

Create:

- Initial introduction email
- First inquiry response
- Follow-up email
- Consultation invitation
- Qualification checklist
- Lead rejection or polite decline message

### Completion conditions

A lead may be converted into a client only after the administrator confirms the conversion.

Automatically preserve the lead's information and communication history.

---

# 5. MODULE 2 — INITIAL INQUIRY

Develop an inquiry management interface.

### Features

Allow inquiries to be created manually or imported through supported mechanisms.

The system must support:

- Inquiry reference number
- Associated lead or client
- Inquiry date
- Requested website type
- Business description
- Expected features
- Existing website
- Budget range
- Desired launch date
- Preferred communication method
- Additional notes
- Inquiry status

### Inquiry questionnaire

Generate a reusable questionnaire asking:

1. What is your business name?
2. What products or services do you offer?
3. What is the main purpose of your website?
4. Who is your target audience?
5. Do you already have a website?
6. What pages would you like?
7. What features are necessary?
8. Do customers need accounts?
9. Do you need online payments?
10. Do you need appointment scheduling?
11. Do you have a brand identity?
12. Do you own a domain?
13. Do you already have hosting?
14. What is your target budget?
15. When would you like the project completed?

### Automations

- Generate an inquiry acknowledgment email.
- Create an inquiry checklist.
- Create missing-information tasks.
- Identify unanswered questionnaire fields.
- Suggest the next workflow stage.
- Prepare a discovery meeting invitation.

Do not automatically promise a project price or delivery deadline.

### Templates

- Inquiry acknowledgment
- Requirements questionnaire
- Missing information request
- Discovery meeting invitation

### Completion conditions

The initial inquiry stage is complete when the required information is recorded and the developer approves proceeding to discovery.

---

# 6. MODULE 3 — DISCOVERY AND CONSULTATION

Develop a discovery workspace for understanding the client's business and website requirements.

### Features

Record:

- Client business objectives
- Customer demographics
- Business problems
- Existing workflows
- Desired website functionality
- Design preferences
- Competitor references
- Content requirements
- Required integrations
- Security and privacy requirements
- Maintenance expectations
- Budget constraints
- Deadline constraints
- Known technical limitations

### Discovery notes

Allow developers to:

- Create meeting notes.
- Record important decisions.
- Upload reference documents.
- Attach website screenshots.
- Create follow-up tasks.
- Assign action owners.
- Record due dates.
- Mark unresolved questions.

### Automations

After the consultation:

1. Generate a structured discovery summary.
2. Identify missing requirements.
3. Generate a follow-up email draft.
4. Produce a preliminary project requirements document.
5. Prepare a scope-planning checklist.

### Templates

- Discovery questionnaire
- Meeting agenda
- Meeting notes
- Discovery summary
- Requirements specification
- Missing requirements email

### Completion conditions

Require an administrator-reviewed requirements summary before proceeding.

---

# 7. MODULE 4 — SCOPE AND PROJECT PLANNING

Develop a Scope of Work management system.

### Features

Each project must contain:

- Project title
- Project description
- Business objectives
- Included pages
- Included features
- Excluded features
- Deliverables
- Client responsibilities
- Technical requirements
- Design requirements
- Integration requirements
- Content requirements
- Project assumptions
- Constraints
- Dependencies
- Estimated work hours
- Proposed milestones
- Revision allowance
- Acceptance criteria

### Scope builder

Provide a structured interface where the developer can add pages and features.

Each feature must support:

- Feature name
- Description
- Estimated development hours
- Complexity
- Priority
- Dependencies
- Acceptance criteria
- Included or excluded status

### Project planning

Generate a preliminary project schedule based on manually supplied estimates.

Allow the administrator to override all automatically suggested values.

Support milestones such as:

- Requirements approved
- Proposal accepted
- Initial payment received
- Assets received
- Design approved
- Development complete
- Testing complete
- Final acceptance received
- Final payment received
- Website launched
- Handover completed

### Automations

- Generate scope documents.
- Suggest a development timeline.
- Calculate estimated total development hours.
- Create project milestones.
- Detect missing scope details.
- Identify conflicting dependencies.
- Warn about unrealistic schedules.
- Prepare the proposal generation stage.

### Templates

- Scope of Work
- Feature specification
- Project timeline
- Milestone plan
- Technical requirements
- Client responsibilities
- Change request

### Completion conditions

The scope must be explicitly approved before being marked as finalized.

Store approved versions and maintain their revision histories.

---

# 8. MODULE 5 — PROPOSAL AND QUOTATION

Develop a proposal builder and project pricing system.

### Features

Create quotations using:

- Project components
- Estimated work hours
- Hourly rates
- Fixed fees
- Additional expenses
- Discounts
- Applicable taxes
- Contingency amounts
- Recurring expenses
- Total proposed price

Use Decimal arithmetic to prevent financial rounding errors.

### Pricing calculator

Support the formula:

Project Price = Labor + Direct Expenses + Contingency + Applicable Taxes - Discounts

Allow fixed-price quotations when the developer does not want to charge hourly.

### Proposal builder

Automatically populate:

- Client information
- Project overview
- Business objectives
- Proposed solution
- Deliverables
- Included features
- Exclusions
- Timeline
- Pricing
- Payment schedule
- Revision policy
- Assumptions
- Expiration date
- Acceptance instructions

### Features

- Proposal preview
- PDF generation
- Proposal version history
- Draft and approved statuses
- Manual price adjustments
- Proposal expiration tracking
- Quotation comparison
- Client-facing proposal export

### Automations

- Populate a proposal from the approved scope.
- Calculate estimated totals.
- Draft the proposal email.
- Track whether the proposal was sent.
- Schedule follow-up reminders.
- Generate revised proposal versions when pricing changes.

Never mark a proposal accepted merely because an email was sent.

### Templates

- Website development proposal
- Formal quotation
- Revised quotation
- Proposal submission email
- Proposal follow-up email
- Proposal acceptance confirmation

### Completion conditions

Require recorded client acceptance and administrator confirmation.

---

# 9. MODULE 6 — CONTRACT AND DEPOSIT

Develop a contract and payment initiation workspace.

### Contract generation

Support customizable contract templates containing:

- Parties
- Project scope
- Deliverables
- Schedule
- Payment terms
- Revision policy
- Change request policy
- Intellectual property provisions
- Confidentiality
- Cancellation
- Termination
- Warranty
- Maintenance exclusions
- Dispute handling
- Signature fields

Clearly mark generated contracts as drafts requiring professional review.

Do not represent generated legal text as guaranteed legally valid.

### Payment management

Allow administrators to create payment schedules:

- Full upfront payment
- 50/50
- 40/30/30
- Custom milestone payments

### Invoice information

Each invoice must include:

- Invoice number
- Client information
- Project information
- Invoice date
- Due date
- Line items
- Subtotal
- Tax, if applicable
- Discounts
- Total amount
- Amount paid
- Outstanding balance
- Payment instructions
- Status

### Automations

- Generate a contract draft from the approved proposal.
- Generate the initial invoice.
- Draft a deposit payment email.
- Track invoice due dates.
- Suggest payment reminders.
- Record payment confirmations.
- Create a project-start task after the required agreement and deposit conditions are verified.

Do not automatically mark invoices as paid merely because the client reports a payment.

Require verified payment records or explicit administrator confirmation.

### Completion conditions

The project can enter the active implementation stage only after its required contractual and payment conditions are satisfied.

---

# 10. MODULE 7 — CLIENT ONBOARDING

Develop an onboarding management workspace.

### Asset collection

Support:

- Company logo
- Brand colors
- Fonts
- Written content
- Product information
- Service descriptions
- Images
- Videos
- Social media links
- Business address
- Contact details
- Domain information
- Hosting information
- Other supporting documents

### Onboarding checklist

Generate a checklist based on the approved project scope.

Each checklist item must have:

- Name
- Description
- Responsible party
- Required or optional status
- Due date
- Completion status
- Attachment references

### Automations

- Generate onboarding welcome emails.
- Generate asset request emails.
- Remind the administrator about missing client materials.
- Track asset submission deadlines.
- Show missing items on the project dashboard.
- Update onboarding completion progress.

### Security requirements

Do not store plaintext passwords supplied by clients.

Prefer account invitations and delegated access for third-party platforms.

If secure credential storage is required in a future version, use dedicated secrets management rather than ordinary database text fields.

### Completion conditions

Require all critical onboarding materials or documented exceptions before completing the stage.

---

# 11. MODULE 8 — WEBSITE DESIGN AND APPROVAL

Develop a design review and approval workspace.

### Design management

Support:

- Sitemap files
- Wireframes
- Design mockups
- Desktop designs
- Tablet designs
- Mobile designs
- Figma reference links
- Design versions
- Client comments
- Revision requests
- Approval records

### Design revision tracking

Each revision request must contain:

- Request number
- Submitted date
- Description
- Related design file
- Revision category
- Included or billable status
- Resolution notes
- Completion date

Track the number of included revision rounds used.

### Automations

- Generate design review emails.
- Generate design approval requests.
- Remind the administrator about pending approvals.
- Record design review decisions.
- Warn when the agreed revision allowance has been exceeded.
- Create a change request when a proposed modification falls outside the approved scope.

### Templates

- Design submission email
- Design feedback form
- Revision request
- Design approval confirmation
- Design milestone invoice

### Completion conditions

Require explicit design approval before closing the stage.

---

# 12. MODULE 9 — WEBSITE DEVELOPMENT

Develop a project development dashboard.

### Development tracking

Support:

- Development tasks
- Features
- Subtasks
- Milestones
- Estimated hours
- Actual hours
- Task priorities
- Dependencies
- Assigned developers
- Due dates
- Completion percentages
- Blockers
- Code repository references
- Staging URLs
- Deployment environment notes

### Task statuses

- Backlog
- Ready
- In Progress
- Blocked
- In Review
- Testing
- Completed
- Canceled

### Project board

Implement a Kanban-style task board.

Allow tasks to be moved between columns.

Use asynchronous JavaScript requests to update task statuses without refreshing the entire page.

### Development progress calculation

Calculate progress using completed estimated task hours divided by total estimated task hours.

Clearly identify this as a task-estimate-based progress indicator, not a guarantee of actual completion or readiness.

### Automations

- Create development tasks from approved scope items.
- Track overdue tasks.
- Generate weekly project progress summaries.
- Draft progress update emails.
- Highlight blockers.
- Update milestone progress.
- Detect approved scope changes that need additional development tasks.

### Templates

- Weekly progress update
- Development milestone report
- Blocker notification
- Delay notification
- Technical issue report
- Client clarification request

### Completion conditions

Require the agreed development features to be completed and ready for QA.

---

# 13. MODULE 10 — TESTING AND REVISIONS

Develop a complete QA and User Acceptance Testing management workspace.

### Testing categories

- Functional testing
- Responsive testing
- Browser compatibility
- Accessibility
- Performance
- Security
- Form processing
- Email integrations
- Payment integrations, if applicable
- Content verification
- SEO basics
- User acceptance testing

### Test case fields

- Test case ID
- Test name
- Description
- Preconditions
- Steps
- Expected result
- Actual result
- Pass or fail
- Severity
- Tester
- Testing date
- Evidence attachment

### Bug tracking

Each bug must have:

- Bug ID
- Description
- Related feature
- Severity
- Priority
- Reproduction steps
- Expected behavior
- Actual behavior
- Assigned developer
- Status
- Resolution details

### Revision classification

Distinguish among:

1. Defects
2. Included revisions
3. Out-of-scope change requests

### Automations

- Generate standard test cases.
- Create bug records from failed tests.
- Track unresolved critical defects.
- Draft client review invitations.
- Track user acceptance feedback.
- Generate QA reports.
- Create change request drafts for out-of-scope modifications.

### Completion conditions

Do not allow a project to be automatically marked ready for final acceptance if unresolved release-blocking defects remain.

---

# 14. MODULE 11 — FINAL ACCEPTANCE AND PAYMENT

Develop a final acceptance workspace.

### Requirements

Record:

- Final tested version
- Open issues
- Agreed exceptions
- Client acceptance status
- Client acceptance date
- Accepting person's name
- Evidence of written acceptance
- Final invoice
- Outstanding balance

### Automations

- Generate final review emails.
- Generate acceptance request documents.
- Produce final invoices.
- Track pending payments.
- Prepare launch readiness checklists.

### Approval rules

Require explicit administrator verification of client acceptance.

Verify final payment according to the contract's payment schedule.

Do not confuse acceptance of the website with authorization to launch it.

These must be separately recorded when required.

---

# 15. MODULE 12 — DEPLOYMENT AND LAUNCH

Develop a website launch management workspace.

### Deployment records

Track:

- Production URL
- Hosting provider
- Domain registrar
- Deployment date
- Deployment method
- Deployment status
- Backup confirmation
- HTTPS status
- Production environment checks
- Post-deployment testing
- Launch approval
- Rollback plan

### Pre-launch checklist

Include:

- Client approval recorded
- Contractual payment conditions satisfied
- Required functionality tested
- Production configuration completed
- Domain and DNS prepared
- HTTPS active
- Production secrets configured
- Backups available
- Administrative accounts configured
- Required content finalized
- Privacy-related requirements checked
- Launch authorization recorded

### Automations

- Generate launch readiness reports.
- Identify incomplete release requirements.
- Draft launch announcement emails.
- Schedule post-launch verification tasks.
- Record launch completion.

### Critical restriction

The CRM must not automatically deploy, replace, or modify a client's production website merely because a workflow stage changes.

Actual deployment must remain a separately authorized operation.

---

# 16. MODULE 13 — HANDOVER AND TRAINING

Develop a website handover workspace.

### Handover checklist

Support:

- Production URL
- Domain ownership confirmation
- Hosting ownership confirmation
- Administrative account transfer
- Source code delivery, if included
- Design asset delivery, if included
- Documentation
- Backup instructions
- Maintenance requirements
- Third-party licenses
- Training records
- Outstanding obligations

### Documentation generator

Automatically assemble a handover document from approved project data.

### Training records

Track:

- Training date
- Participants
- Topics covered
- Resources provided
- Follow-up questions
- Training completion status

### Automations

- Generate handover checklists.
- Generate project completion reports.
- Draft website handover emails.
- Generate documentation cover pages.
- Schedule warranty expiration reminders.
- Prepare project closure records.

### Completion conditions

Require confirmation that the agreed handover deliverables were provided.

---

# 17. MODULE 14 — MAINTENANCE AND SUPPORT

Develop an optional maintenance management module.

### Maintenance contracts

Support:

- Maintenance plan name
- Client
- Website
- Monthly fee
- Billing frequency
- Start date
- Renewal date
- Covered services
- Excluded services
- Support hours
- Response expectations
- Contract status

### Support ticket management

Each support ticket must contain:

- Ticket number
- Client
- Related website
- Issue category
- Description
- Priority
- Status
- Submitted date
- Assigned developer
- Resolution
- Time spent

### Ticket statuses

- Open
- Investigating
- Awaiting Client
- In Progress
- Resolved
- Closed

### Maintenance activities

Track:

- Software updates
- Backup checks
- Security checks
- Content updates
- Performance reviews
- Uptime incidents
- Plugin updates
- Domain renewal dates
- Hosting renewal dates

### Automations

- Generate recurring maintenance tasks.
- Draft maintenance reports.
- Prepare renewal notices.
- Track subscription invoices.
- Generate follow-up recommendations.
- Track warranty expiration dates.

Do not claim that maintenance checks were performed unless the checks have verifiable execution records or human confirmation.

---

# 18. CENTRAL CLIENT MANAGEMENT MODULE

Create a centralized CRM that connects all stages.

Each client profile must display:

- Personal and business contact information
- Active projects
- Completed projects
- Lead history
- Inquiry history
- Email history
- Meeting notes
- Contracts
- Proposals
- Invoices
- Payments
- Files
- Support tickets
- Maintenance subscriptions
- Activity timeline

Clicking a client should display their full history and allow navigation to their projects.

Add search, filtering, sorting, and archiving.

Use soft deletion for important business records where appropriate, with retention and deletion controls.

---

# 19. EMAIL AUTOMATION SYSTEM

Develop a dedicated email management module using yagmail.

### Email configuration

Store configuration such as:

- Sender address
- Sender display name
- SMTP configuration
- Reply-to address
- Email signature
- Business name
- Default time zone

Store credentials through environment variables or secure deployment configuration.

Do not put email passwords in SQLite plaintext columns.

### Email templates

Create editable templates for all lifecycle stages.

Every template must support variables such as:

- {{client_name}}
- {{business_name}}
- {{project_name}}
- {{project_id}}
- {{project_status}}
- {{invoice_number}}
- {{invoice_amount}}
- {{invoice_due_date}}
- {{milestone_name}}
- {{developer_name}}
- {{business_email}}

Validate template variables and safely handle missing values.

### Email composition

Build an internal email composer with:

- Recipient
- Subject
- Body
- Template selector
- Preview
- Draft saving
- Attachments
- Send button
- Send status
- Error reporting

Support rich HTML templates and a plain-text alternative.

### Email automation types

1. Manual email
2. Automatically generated draft
3. Scheduled email requiring approval
4. Explicitly authorized transactional automation

Examples of transactional automation include routine project status notifications and payment reminders, subject to configured rules and applicable consent requirements.

### Approval workflow

Use the following:

Event occurs
→ Automation evaluates conditions
→ Email draft is generated
→ Administrator reviews, edits, and approves
→ Email is queued
→ Email is sent
→ Delivery attempt is logged

For approved automatic emails, allow the administrator to configure clearly defined sending rules.

### Email tracking

Record:

- Email ID
- Associated client
- Associated project
- Recipient
- Subject
- Rendered body or secure body reference
- Template ID
- Creation date
- Scheduled time
- Sent time
- Sending status
- Delivery provider response
- Failure reason

Do not mark an email as opened or read unless a legitimate and properly disclosed tracking mechanism supports that status.

A successful SMTP submission does not guarantee inbox delivery.

### Incoming email limitations

yagmail is primarily an email-sending library.

Do not pretend it automatically reads incoming messages or detects client replies.

Implement a separate optional incoming-email adapter using an explicitly configured Gmail API or IMAP integration if inbound synchronization is required.

Otherwise, allow incoming messages and client responses to be recorded manually.

### Reliability

Implement:

- Send queues
- Retry policies
- Maximum retry limits
- Duplicate-send protection
- Error logs
- Scheduled sending
- Email opt-out and suppression controls where applicable
- Test-email mode
- Administrator-controlled automation pause

---

# 20. DOCUMENT TEMPLATE ENGINE

Develop a centralized template management system.

Support creating, editing, duplicating, previewing, archiving, and exporting templates.

### Required templates

**Sales and discovery**
- Lead inquiry form
- Discovery questionnaire
- Consultation notes
- Requirements document

**Project planning**
- Scope of Work
- Project timeline
- Milestone plan
- Feature specification

**Commercial**
- Project proposal
- Quotation
- Development agreement
- Invoice
- Payment reminder
- Receipt or payment acknowledgment, as appropriate

**Design and development**
- Design feedback form
- Design approval
- Weekly progress report
- Change request
- Bug report

**Delivery**
- QA report
- UAT checklist
- Acceptance form
- Launch checklist
- Handover document
- Project completion report

**Support**
- Maintenance agreement
- Support ticket
- Maintenance report
- Renewal reminder

### Template engine features

- Dynamic variable substitution
- Client and project data binding
- Template categories
- Template versioning
- Document preview
- PDF export
- Markdown export where appropriate
- Optional company branding
- Draft and finalized statuses
- Document history

Ensure templates are escaped appropriately and that untrusted content cannot execute code.

---

# 21. FINANCIAL MANAGEMENT

Build a financial dashboard.

### Financial information

Track:

- Quoted revenue
- Contracted project value
- Invoiced amounts
- Verified received payments
- Outstanding balances
- Overdue invoices
- Project expenses
- Recurring revenue
- Maintenance subscriptions

### Financial charts

Display:

- Monthly revenue
- Monthly expenses
- Outstanding receivables
- Revenue by client
- Revenue by project
- Revenue by service type
- Paid versus unpaid invoices

### Financial rules

Never count quotations as earned revenue.

Distinguish:

- Proposed amounts
- Contracted amounts
- Invoiced amounts
- Collected payments

Calculate balances and totals consistently using Decimal arithmetic.

Provide configurable currency formatting, with Philippine peso as the default.

Do not label a financial report as a legally compliant tax or accounting statement without the necessary business rules and verification.

---

# 22. TASKS, CALENDAR, AND REMINDERS

Create a unified task and schedule management system.

### Task fields

- Task title
- Description
- Associated client
- Associated project
- Workflow stage
- Priority
- Due date
- Status
- Assigned user
- Notes
- Completion date

### Calendar

Display:

- Project milestones
- Meetings
- Invoice due dates
- Client follow-ups
- Design deadlines
- Development deadlines
- Maintenance activities
- Warranty expiration dates

### Automation

Generate tasks from workflow events.

Examples:

- Proposal accepted → Generate contract preparation task.
- Contract approved → Generate initial invoice task.
- Deposit verified → Generate onboarding task.
- Design approved → Generate development milestone tasks.
- QA passed → Generate client acceptance request task.
- Launch completed → Generate handover task.
- Handover completed → Generate warranty follow-up task.

Tasks must not duplicate when the same workflow event is processed more than once.

---

# 23. DASHBOARDS AND ANALYTICS

Develop multiple dashboard views.

### Main dashboard

Show:

- Total clients
- Active leads
- Active projects
- Projects awaiting approval
- Overdue tasks
- Outstanding invoices
- Upcoming milestones
- Pending email drafts
- Recent activity
- Monthly revenue

### Client dashboard

Show an individual client's projects, payments, messages, documents, and action history.

### Project dashboard

Show:

- Current lifecycle stage
- Project progress
- Contract value
- Payment progress
- Next milestone
- Current blockers
- Outstanding approvals
- Overdue tasks
- Project files
- Activity timeline

### Analytics dashboard

Provide charts for:

- Lead conversion
- Project completion
- Average project duration
- Project stage distribution
- Revenue trends
- Client acquisition channels
- Maintenance revenue
- Overdue invoice trends

Include date filters and CSV exports.

---

# 24. USER INTERFACE AND USER EXPERIENCE

Create a modern, professional business application.

### Main layout

Left sidebar:

- Dashboard
- Leads
- Clients
- Inquiries
- Projects
- Tasks
- Calendar
- Proposals
- Contracts
- Invoices
- Payments
- Email Center
- Documents
- Maintenance
- Analytics
- Settings

Top navigation:

- Global search
- Quick actions
- Notifications
- User menu

### UI requirements

- Responsive desktop and mobile layouts
- Clean typography
- Consistent spacing
- Accessible contrast
- Clear navigation
- Light and dark mode
- Searchable tables
- Filters and sorting
- Status indicators
- Modal dialogs
- Toast notifications
- Confirmations for destructive actions
- Loading indicators
- Empty states
- Friendly validation messages

### Project lifecycle interface

Each project must have a visual lifecycle timeline.

Selecting a stage should display:

- Stage description
- Requirements
- Checklist
- Required documents
- Email templates
- Pending tasks
- Completed tasks
- Approvals
- Next actions

Include a prominent "Complete Stage" action.

This action must verify the stage completion requirements before allowing progression.

---

# 25. DATABASE DESIGN

Create relational SQLAlchemy models.

At minimum, implement:

- User
- Lead
- Client
- Contact
- Inquiry
- Project
- ProjectStage
- StageTransition
- Requirement
- ScopeItem
- ProjectMilestone
- Task
- TaskDependency
- Proposal
- ProposalItem
- Contract
- Invoice
- InvoiceItem
- Payment
- Expense
- Document
- DocumentTemplate
- FileAttachment
- EmailTemplate
- EmailDraft
- EmailMessage
- EmailQueue
- EmailAutomationRule
- ScheduledJob
- Meeting
- MeetingNote
- DesignSubmission
- RevisionRequest
- ChangeRequest
- Approval
- TestCase
- TestExecution
- BugReport
- DeploymentRecord
- HandoverRecord
- TrainingRecord
- MaintenanceAgreement
- MaintenanceTask
- SupportTicket
- Notification
- ActivityLog
- AuditLog
- ApplicationSetting

### Database requirements

- Primary keys
- Foreign keys
- Proper relationships
- Unique constraints
- Indexes
- Creation timestamps
- Modification timestamps
- Status values
- Referential integrity
- Validation
- Migration support
- Safe handling of deletion and archival

Financial records must preserve historical amounts.

Do not silently overwrite issued invoices, executed contracts, or finalized approval records.

Use new versions, corrections, or adjustment records when appropriate.

---

# 26. AUTOMATION ENGINE

Build a centralized rule-based automation system.

Each rule must contain:

- Rule ID
- Rule name
- Description
- Trigger event
- Conditions
- Action
- Enabled status
- Approval requirement
- Last executed time
- Execution result

### Example rule

Trigger:
A proposal changes to Accepted.

Conditions:
- Proposal has a valid approval record.
- The project is active.
- No contract preparation task already exists.

Actions:
- Create contract preparation task.
- Generate contract draft.
- Create administrator notification.
- Update the workflow readiness indicators.

### Reliability requirements

- Idempotent operations
- Transaction-safe database changes
- Automation execution logs
- Error handling
- Retry policies
- Prevention of duplicate actions
- Ability to disable automations
- Administrator override controls

### Important scheduler limitation

APScheduler inside a locally running Flask application only performs work while the relevant process is running.

Design scheduled jobs so they are not silently assumed to execute while the developer's computer is turned off.

Use a single dedicated scheduler process or another safe architecture that prevents multiple Flask workers from running the same job.

For reliable 24/7 scheduling, document how to deploy a persistent scheduler service.

---

# 27. SECURITY REQUIREMENTS

Implement:

- Secure login
- Password hashing
- CSRF protection
- Session security
- Role-based authorization where applicable
- Server-side input validation
- File upload validation
- Safe file storage
- Protection against SQL injection
- Protection against XSS
- Secure error handling
- Rate limiting for authentication and public endpoints
- Secrets stored outside source control
- Activity and audit logging
- Backup and restoration procedures
- Protection against unauthorized access to client files

### Uploaded documents

Validate:

- File type
- File size
- Filename
- Storage destination
- Access permissions

Do not trust user-provided filenames or MIME types.

### Data protection

Implement data export, retention policies, and deletion workflows.

Protect client personal information and ensure the application supports compliance with applicable privacy requirements.

Do not place confidential client data into ordinary error logs.

---

# 28. PROPOSED PROJECT STRUCTURE

Use a modular directory structure similar to:

```text
webdev-crm/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── extensions.py
│   ├── models/
│   ├── blueprints/
│   │   ├── auth/
│   │   ├── dashboard/
│   │   ├── leads/
│   │   ├── clients/
│   │   ├── inquiries/
│   │   ├── projects/
│   │   ├── proposals/
│   │   ├── contracts/
│   │   ├── invoices/
│   │   ├── payments/
│   │   ├── tasks/
│   │   ├── email/
│   │   ├── documents/
│   │   ├── approvals/
│   │   ├── qa/
│   │   ├── maintenance/
│   │   ├── analytics/
│   │   └── settings/
│   ├── services/
│   │   ├── lifecycle_service.py
│   │   ├── automation_service.py
│   │   ├── email_service.py
│   │   ├── document_service.py
│   │   ├── invoice_service.py
│   │   ├── notification_service.py
│   │   └── reporting_service.py
│   ├── automations/
│   ├── forms/
│   ├── templates/
│   │   ├── layouts/
│   │   ├── components/
│   │   ├── dashboard/
│   │   ├── clients/
│   │   ├── projects/
│   │   ├── email/
│   │   └── documents/
│   ├── static/
│   │   ├── css/
│   │   ├── js/
│   │   └── images/
│   └── utils/
├── migrations/
├── tests/
├── instance/
├── storage/
│   ├── uploads/
│   ├── exports/
│   └── backups/
├── scheduler/
├── scripts/
├── requirements.txt
├── .env.example
├── .gitignore
├── run.py
└── README.md
```

Refine the structure where necessary while maintaining a clean separation of concerns.

---

# 29. REQUIRED PAGE ROUTES

Implement logical routes such as:

- /login
- /dashboard
- /leads
- /leads/new
- /clients
- /clients/new
- /clients/<id>
- /projects
- /projects/new
- /projects/<id>
- /projects/<id>/lifecycle
- /projects/<id>/scope
- /projects/<id>/design
- /projects/<id>/development
- /projects/<id>/testing
- /projects/<id>/launch
- /projects/<id>/handover
- /proposals
- /contracts
- /invoices
- /payments
- /tasks
- /calendar
- /email
- /email/templates
- /documents
- /documents/templates
- /maintenance
- /support
- /analytics
- /settings
- /settings/automations

All ID-based routes must validate both resource existence and the user's authorization to access that resource.

---

# 30. IMPLEMENTATION ROADMAP

Build the application incrementally.

### Phase 1 — Foundation

Implement:

- Project structure
- Flask application factory
- Database configuration
- SQLAlchemy models
- Database migrations
- Authentication
- Main layout
- Dashboard shell
- Settings

### Phase 2 — CRM

Implement:

- Leads
- Clients
- Inquiries
- Discovery records
- Client activity timeline

### Phase 3 — Project Lifecycle

Implement:

- Projects
- Lifecycle stages
- Stage transition rules
- Requirements
- Checklists
- Tasks
- Milestones
- Scope management

### Phase 4 — Commercial Operations

Implement:

- Proposals
- Quotations
- Contracts
- Invoices
- Payments
- Financial calculations

### Phase 5 — Communications

Implement:

- Email templates
- yagmail integration
- Email drafts
- Approval queue
- Email logs
- Scheduler
- Automation engine

### Phase 6 — Delivery Management

Implement:

- Onboarding
- Design reviews
- Revision tracking
- Development task board
- QA
- Bug tracking
- Acceptance
- Launch
- Handover

### Phase 7 — Support and Analytics

Implement:

- Maintenance
- Support tickets
- Recurring invoices
- Financial dashboards
- Project analytics
- Reports and CSV exports

### Phase 8 — Production Readiness

Implement:

- Security hardening
- Automated tests
- Backup/restore tests
- Error monitoring
- Integration tests
- UI testing
- Deployment documentation
- Example data
- Final documentation

Do not begin the next phase while critical functionality in the current phase is broken.

---

# 31. TESTING REQUIREMENTS

Use pytest for automated backend tests.

Test at least:

- Authentication
- Client CRUD operations
- Lead conversion
- Project creation
- Lifecycle transitions
- Scope approval conditions
- Proposal calculations
- Invoice calculations
- Payment balance updates
- Template rendering
- Email draft generation
- Email queue behavior
- Scheduled task handling
- Duplicate automation prevention
- File access permissions
- Approval workflows
- Change requests
- Bug tracking
- Maintenance scheduling

Mock external SMTP calls so automated tests cannot accidentally email real people.

Use separate test databases and development configuration.

Implement an end-to-end test following a fictional lead from first inquiry to completed website handover.

---

# 32. DEMONSTRATION DATA

Create a development-only seed command with fictional data.

Example:

Client: Luna Coffee House

Project: Business Website Development

Project value: PHP 15,000

Features:
- Homepage
- Menu
- About page
- Contact page
- Contact form
- Maps integration
- Mobile responsiveness

Payment schedule:
- 40% initial
- 30% design approval
- 30% final acceptance

Populate representative:

- Leads
- Clients
- Projects
- Tasks
- Proposals
- Invoices
- Payments
- Emails
- Documents
- Approvals
- Bugs
- Maintenance agreements

Seed data must be clearly labeled as demonstration data.

Do not mix development records with production information.

---

# 33. DOCUMENTATION

Provide complete setup and user documentation.

Include:

1. System overview
2. Installation instructions
3. Virtual environment setup
4. Dependency installation
5. Environment configuration
6. SQLite database initialization
7. Flask migration commands
8. Application startup
9. Scheduler startup
10. SMTP/yagmail configuration
11. Email test procedure
12. Client creation instructions
13. Project workflow instructions
14. Document template editing
15. Payment recording
16. Backup and restoration
17. Troubleshooting
18. Production deployment considerations

Document any manually required setup steps.

Never claim that integrations are configured or functioning without actual verification.

---

# 34. DEVELOPMENT OUTPUT REQUIREMENTS

Build the complete application in working increments.

For each phase:

1. Explain the implementation objective.
2. Identify files being created or modified.
3. Implement functional backend code.
4. Implement required database models.
5. Implement HTML templates.
6. Implement CSS and JavaScript.
7. Connect frontend elements to actual backend routes.
8. Add validation and error handling.
9. Add automated tests.
10. Run available checks.
11. Report which features are operational.
12. Report any incomplete or unverified functionality.

Avoid placeholder buttons that do nothing.

Avoid fake dashboard metrics that appear to be real business data.

Avoid silently ignoring failed operations.

Use consistent naming conventions and maintainable code.

When a feature depends on a third-party service or credentials that are unavailable, build a clearly labeled configuration interface and provide working test-mode behavior where reasonable.

Do not invent successful test results or completed integrations.

---

# 35. FINAL ACCEPTANCE CRITERIA

The application is complete when the administrator can:

1. Create a lead.
2. Qualify and convert the lead into a client.
3. Record the initial inquiry.
4. Conduct and document discovery.
5. Define a project scope.
6. Generate and revise a proposal.
7. Record proposal acceptance.
8. Generate a contract.
9. Create an initial invoice.
10. Verify an initial payment.
11. Begin client onboarding.
12. Manage design submissions and approval.
13. Track website development.
14. Manage testing and revisions.
15. Record final acceptance.
16. Generate the final invoice.
17. Record verified final payment.
18. Track deployment and launch.
19. Generate handover documents.
20. Close the project.
21. Offer and manage maintenance.
22. View financial and project analytics.
23. Generate and approve email drafts.
24. Send authorized emails through yagmail.
25. View email and activity logs.
26. Export important documents and data.
27. Search all relevant client and project records.
28. Recover from common errors without corrupting project data.

All lifecycle stages must operate as one connected system.

The purpose of WebDev CRM is to reduce administrative work so the developer can concentrate on delivering websites while maintaining professional client communication, financial oversight, organized documentation, and reliable project operations.

Begin with the architecture, database design, and Phase 1 implementation, then continue systematically through the roadmap while ensuring each phase remains functional.

# Hanami user guide

## Start with your workspace

Sign in with the administrator account created from the command line. The dashboard reports data from your database: upcoming work, pending reviews, invoices, email drafts, and recent activity. Use the sidebar to open each workspace. Search finds relevant records; the calendar combines scheduled work. Settings control business details and automation preferences. The theme control switches between light and dark mode.

All business dates are stored in UTC. The configured display timezone defaults to Asia/Manila. Amounts use decimal arithmetic and show their currency. A dashboard figure is an operational summary, not an accounting or tax filing.

## From lead to client

1. Open **Leads → New lead** and record the contact, business, source, requested service, budget, and follow-up information. Qualification work and an introduction draft are prepared for review.
2. Keep the lead's status and next follow-up current. Review email drafts in the Email Center before any send action.
3. When ready, deliberately confirm **Convert to client**. The client keeps the original lead relationship and recorded history. Conversion can be repeated safely without creating a second client.
4. Open the client to maintain details and contacts, review the activity history, and create a project.
5. Create an inquiry linked to the lead, client, and project as appropriate. Complete the questionnaire and record missing information explicitly.

Archive records when you need to remove them from active work while preserving financial and approval history. Do not use ordinary notes to store client passwords. Arrange account invitations or delegated access instead.

## Work through a project

Every new project contains fourteen stages. The lifecycle timeline links to each stage's workspace. Save required information, complete each required checklist item or record a specific exception, record evidence of approval, and then choose **Complete stage**. The server checks the underlying commercial and delivery records as well as the checklist.

| Stage | Information and evidence to record |
| --- | --- |
| 1. Client acquisition | Qualification summary, requested service, and confirmed conversion. |
| 2. Initial inquiry | Website type, audience, features, budget, and reviewed questionnaire. |
| 3. Discovery and consultation | Business objectives, reviewed requirements, constraints, consultation decisions, and unresolved questions. |
| 4. Scope and planning | Deliverables, exclusions, client responsibilities, feature estimates and acceptance criteria, milestones, and separate scope approval. |
| 5. Proposal and quotation | Timeline, payment schedule, an accepted proposal, and the client's acceptance evidence. |
| 6. Contract and deposit | An executed contract, an issued deposit invoice, and enough verified payments to settle it. |
| 7. Client onboarding | Brand/content assets, delegated access, and evidence for any missing-material exceptions. |
| 8. Design and approval | Versioned submissions, feedback, resolved revisions, and explicit design approval. |
| 9. Website development | Agreed development tasks completed, feature readiness, staging reference, and development summary. |
| 10. Testing and revisions | Test cases and current executions, QA summary, tested version, and resolved release-blocking defects. |
| 11. Final acceptance and payment | Written acceptance with administrator verification, final invoice, and all balances settled with verified payments. |
| 12. Deployment and launch | Separate launch authorization, production URL, rollback plan, deployment record, and completed production checks. |
| 13. Handover and training | Delivered documentation, account ownership transfer, training or evidenced waiver, warranty terms, and completed handover. |
| 14. Maintenance and support | A maintenance agreement or explicit decline, support expectations, and recorded maintenance decision. |

A stage approval includes a person's name and supporting evidence. For client-facing decisions, record the client's written decision and the administrator's verification. A draft document or an email send event is not approval.

Use **Return to stage** with a reason when work must be reopened. Reopening preserves decision history and invalidates later stage completion; review the affected work and record fresh approvals. Pause or cancel a project deliberately rather than changing checklists to conceal a blocker.

## Scope, estimates, and development

Add included and excluded scope items with hours, rate, complexity, priority, dependencies, and acceptance criteria. Record a milestone plan and obtain scope approval. Estimates assist planning and can be changed through the appropriate reviewed workflow; they are not guaranteed delivery dates.

The development board organizes tasks by status. Task dependencies prevent completion while prerequisites remain open. Estimated-hours progress measures completed estimated work; verify actual readiness separately. Track changed scope in a change request with its cost and schedule impact before approving additional development.

## Proposals, contracts, and payments

Build a proposal from project scope or provide fixed-price items. Review labor, expenses, contingency, tax, and discounts. Export and review the PDF. Preserve revisions as separate versions, and record acceptance with the person and evidence after the client agrees.

Generate a contract from the approved proposal, review and customize its clauses, and obtain professional review where needed. Record execution only after confirming the parties' agreement. Keep signed evidence with the project.

Create and issue the required invoices. Record received payment details against the correct invoice, then separately verify them against your bank or payment provider. Unverified payments do not reduce the verified balance or unblock the lifecycle. Sending a reminder or receiving a client's claim of payment never marks an invoice paid. Preserve issued amounts and use documented corrections instead of rewriting financial history.

## Designs, QA, launch, and handover

Submit each design as a new version with its reference link and notes. Record feedback and revision requests; identify billable scope changes when the agreed revision allowance is exceeded. Record approval of the actual submitted version.

Create QA cases with steps and expected results. Record actual executions with the tester, result, and evidence. File defects with severity and reproduction instructions, and verify the fixes. Required tests and unresolved release blockers appear in the lifecycle's completion checks.

Launch records document a deployment you carry out using your normal hosting tools. Verify the authorized version, rollback plan, HTTPS, DNS, backup, privacy/content checks, and post-launch behavior. The CRM does not execute a deployment itself.

At handover, record deliverables, ownership transfers, documentation, training, client confirmation, and warranty expectations. Generate a handover document and keep acknowledgement evidence. Complete the maintenance decision stage to close the project lifecycle.

## Email and documents

Templates are editable in **Email → Templates** and **Documents → Templates**. Template variables draw from the associated client and project. Review rendered content and recipient addresses before approval. Maintain contractual text with appropriate professional review.

Use drafts to prepare introductions, questionnaires, proposals, updates, and reminders. Approval is a separate action before queueing delivery. The Email Center records simulated, sent, failed, or pending outcomes. In test mode, a simulated send remains a simulation. For live SMTP, follow the [test procedure](deployment.md#email-test-procedure) and inspect the resulting record.

Upload permitted supporting files through Documents. Files are stored privately and downloads require an administrator session. The application validates file type and size; keep passwords and secret tokens out of files and notes. PDF document exports capture reviewed business information; export again after creating a new document version.

## Maintenance, support, and reporting

Record maintenance agreements with their service terms, renewal dates, and recurring fee where applicable. Use maintenance tasks for routine checks and support tickets for reported issues. Keep ticket priority, status, and resolution notes current. Scheduler-generated work is visible and must still be reviewed.

Analytics reports use recorded operational data. Use date filters and CSV exports for external analysis. Export only to an appropriately protected location because client details and business records are sensitive. The application provides archival, data export, and an operator-only limited contact anonymization command after the retention period. It preserves historical financial, approval, email, document, log, and backup evidence. Set a documented retention policy and review the wider retained records before any erasure request; see the operations guide for the command and its safeguards.

## Recover from an error

Validation errors describe missing or inconsistent input and leave the previous committed records intact. Retry after correcting the identified problem. For email failures, check the delivery record and SMTP settings; do not repeatedly resend without checking whether a remote service already accepted the message. For database or file failures, stop writes, inspect a private operational log, and follow the [backup and restore instructions](deployment.md#backup-and-restore).

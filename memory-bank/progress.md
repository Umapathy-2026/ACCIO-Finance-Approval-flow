Completed and working
- Core authentication (login/logout, CSRF tokens, password strength checks, lockout)
- Ticket creation with dynamic IssueForm fields and attachments
- Approver queues and actions (approve/reject/send back/reassign)
- Admin console (dashboard metrics, user management, form CRUD, audit log)
- Email notifications on ticket creation and clarification (best-effort)
- Excel exports for tickets and audit logs
- Rate limiting with sane defaults

In progress
- None identified today

Not yet started / potential roadmap
- Move rate-limit storage to Redis for production scale-out
- Introduce Alembic for database migrations
- Add unit/integration tests for core flows
- Improve attachment virus scanning and content-type validation
- Enhance dashboards with charts and filters
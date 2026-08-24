# CrawlerAI AWS Production Owner Runbook

**State:** NOT APPROVED FOR PRODUCTION TRAFFIC
**Prepared:** 2026-08-24
**Applies to:** the future `crawlerai-demo` AWS stack and its Cloudflare hosts
**Evidence rule:** never mark a row PASS without a dated, immutable evidence reference

This runbook owns production closeout for the security and AWS implementation
plans. It contains no secret values. Store evidence as protected GitHub workflow
run URLs, sanitized artifacts, Cloudflare change references, or AWS console/API
references. Never paste credentials, tokens, cookies, database contents, or
unredacted logs here.

## Named Owners

Production remains NO-GO until each role names one accountable person and backup.

| Role | Accountable person | Backup | Evidence channel |
| --- | --- | --- | --- |
| Release and rollback owner | UNASSIGNED | UNASSIGNED | Protected GitHub `aws-demo` environment |
| AWS infrastructure and IAM owner | UNASSIGNED | UNASSIGNED | AWS change record |
| Cloudflare and DNS owner | UNASSIGNED | UNASSIGNED | Cloudflare change record |
| Database restore owner | UNASSIGNED | UNASSIGNED | Restore drill record |
| Security/risk acceptance owner | UNASSIGNED | UNASSIGNED | Written risk decision |
| Incident owner | UNASSIGNED | UNASSIGNED | Incident channel/runbook reference |

The read-only AWS principal observed during preparation proves account access only.
It does not assign an operational owner or authorize provisioning.

## Release Evidence Register

Fill every field. `PENDING` and `BLOCKED` fail the production gate.

| Gate | Required proof | Owner | Evidence reference | Observed UTC | Expiry UTC | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Immutable image digests | ECR digest, SBOM, Trivy and enhanced-scan gates | UNASSIGNED | none | not run | n/a | BLOCKED |
| Cloudflare Full (strict) | Zone setting and valid origin certificate/SAN | UNASSIGNED | none | not run | n/a | BLOCKED |
| Proxied DNS and HTTPS | Proxied records and external DNS/TLS output | UNASSIGNED | none | not run | n/a | BLOCKED |
| WebSocket/SSE | Authenticated external stream completes | UNASSIGNED | none | not run | n/a | BLOCKED |
| Cache policy | API/HTML no-cache and hashed static cache headers | UNASSIGNED | none | not run | n/a | BLOCKED |
| Edge body/rate controls | Allowed control plus bounded rejection triggers | UNASSIGNED | none | not run | n/a | BLOCKED |
| Cloudflare-only origin | Normal proxy path works; direct ALB path denied | UNASSIGNED | none | not run | n/a | BLOCKED |
| RDS backups/PITR | Encrypted private configuration and recovery point | UNASSIGNED | none | not run | n/a | BLOCKED |
| Disposable RDS restore | Restore validation and cleanup record | UNASSIGNED | none | not run | n/a | BLOCKED |
| Redis TLS/auth | `rediss://` success and plaintext/anonymous denial | UNASSIGNED | none | not run | n/a | BLOCKED |
| EFS encryption/access points | Encrypted, task-scoped mounts | UNASSIGNED | none | not run | n/a | BLOCKED |
| Logs and alarms | Retention, redaction, ALARM and OK evidence | UNASSIGNED | none | not run | n/a | BLOCKED |
| Secret rotation | Rotate, deploy, verify, revoke-old sequence | UNASSIGNED | none | not run | n/a | BLOCKED |
| Least-privilege roles | Role matrix and negative access checks | UNASSIGNED | none | not run | n/a | BLOCKED |
| Failed migration | Nonzero migration blocks all service rollout | UNASSIGNED | none | not run | n/a | BLOCKED |
| Controlled rollback | Prior compute revisions restored; data unchanged | UNASSIGNED | none | not run | n/a | BLOCKED |
| Demo stop/start | Data retained and cache expectation recorded | UNASSIGNED | none | not run | n/a | BLOCKED |

## Cloudflare Closeout

Run only after the AWS plan provisions a validated ALB and hosts.

1. Record zone, frontend/API hosts, ALB output, certificate ARN, and change ID.
2. Confirm both records are proxied. Confirm Full (strict) and Always Use HTTPS.
3. Externally verify certificate chain, exact SANs, frontend, `/health/live`, and
   unauthenticated `/health/ready` (200 ready, 503 not ready).
4. Verify API and HTML are not cached. Verify hashed frontend assets use the
   repository cache contract.
5. Run authenticated WebSocket/SSE checks. Record duration, completion, status,
   and request ID without credentials or payload data.
6. Test one request at the body boundary and one byte over. Test a legitimate
   low-rate control and a bounded rate-limit trigger.
7. Restrict ALB 443 ingress to current Cloudflare IPv4/IPv6 ranges. Repeat proxy
   checks, then prove direct ALB/origin access is denied.
8. Keep the prior deployment until the recorded rollback window ends.

Full-mode downgrade, gray-cloud DNS, origin bypass, cached API data, or broken
streaming is an automatic NO-GO.

## AWS Data and Runtime Closeout

Use sanitized AWS `describe-*` output or protected workflow artifacts as proof.

- RDS: private, encrypted, deletion-protected, PITR-enabled, current recovery point,
  and no public security-group path.
- Redis: private, encrypted in transit/at rest, AUTH/ACL enabled, and only required
  API/worker/migration security groups admitted.
- EFS: encrypted and mounted through task-specific access points with least-
  privilege POSIX identities and security groups.
- ECS: API, worker, migration, scheduler, frontend, and execution roles have
  separate secret/IAM scopes. Negative checks deny unrelated access.
- CloudWatch: bounded retention and redaction checks pass. Alarm tests cover ALB,
  ECS, migration, queue, RDS, Redis, EFS, and missed cleanup.

## Disposable Restore Drill

This gate must not replace or mutate the source database.

1. Record an automated recovery point, source identifier, and UTC.
2. Restore to a uniquely named disposable instance in private subnets, with no
   public access and an isolated security group.
3. Connect only from the validation task. Check migration status, row counts,
   bootstrap consumption, and sentinel-record integrity. Never export row data.
4. Record start/end, recovery point, validation results, and sanitized logs.
5. After exact-target review, delete only the disposable target. Record deletion
   and confirm the source instance was untouched.

Any restore, private-connectivity, integrity, or cleanup failure is NO-GO.

## Controlled Rollback Drill

Rollback changes compute revisions only. It never downgrades Alembic automatically.

1. Record current and prior immutable digests and ECS task revisions.
2. Deploy a controlled reversible revision through the protected workflow.
3. Verify stability and authenticated readiness.
4. Invoke rollback. Confirm prior API/frontend/worker revisions and digests.
5. Verify readiness, one queued crawl, frontend deep-link, and stream behavior.
6. Confirm RDS, Redis, EFS, secrets, and Terraform state were not replaced.

If schema rollback is required, stop. Use an approved forward-fix or data-restore
incident decision.

## Migration Failure and Demo Controls

- Migration: fail safely only in rehearsal. It must exit nonzero before any service
  update; existing service revisions stay live.
- Stop: scale application services/tasks to zero through the control workflow. Stop
  RDS only where supported. Do not destroy RDS, EFS, or state. Record Redis loss.
- Start: restore RDS first, then services in dependency order. Wait for readiness,
  worker ping, scheduled-task registration, and authenticated smoke checks.

## Secret Rotation

For JWT signing, application encryption, bootstrap, metrics, Redis, provider, proxy,
and API credentials, record owner, method, affected services, overlap/revocation,
verification, and next rotation date. Generate CrawlerAI-specific values. Never copy
Invoro values. Remove the one-time bootstrap password after bootstrap.

## Residual Risks and Expiry

An exception is valid only with every column filled and explicit security-owner
approval. Expired acceptance blocks release.

| Risk ID | Priority | Risk | Owner | Acceptance | Accepted UTC | Expires UTC | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OPS-01 | P2 | Live ECR enhanced findings are not classified | UNASSIGNED | none | not accepted | not set | OPEN |
| OPS-02 | P2 | AWS private-data and least-privilege controls do not exist | UNASSIGNED | none | not accepted | not set | OPEN |
| OPS-03 | P2 | Cloudflare controls and origin denial are unproved | UNASSIGNED | none | not accepted | not set | OPEN |
| OPS-04 | P2 | Restore and rollback drills have not run | UNASSIGNED | none | not accepted | not set | OPEN |
| OPS-05 | P2 | Operational owners are unassigned | UNASSIGNED | none | not accepted | not set | OPEN |

These are blockers, not accepted risks. Do not invent an expiry to make an
unaccepted risk appear bounded.

## GO/NO-GO Decision

GO requires every evidence row PASS, no open P0/P1, no unaccepted P2, successful
restore and rollback, named primary/backup owners, and no expired acceptance. Record
approving release/security owners, immutable digests, decision UTC, and rollback end.

**Current decision: NO-GO.** The AWS plan is queued, its stack and Cloudflare controls
do not exist, live drills have not run, and operational owners are unassigned.

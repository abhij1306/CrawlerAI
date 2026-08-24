# Plan: CrawlerAI AWS Codex Implementation

**Created:** 2026-08-24
**Agent:** Codex
**Status:** QUEUED
**Touches buckets:** containers, Terraform/AWS, IAM/OIDC, GitHub Actions, Cloudflare, deployment, observability, operations

## Goal

Deploy CrawlerAI on AWS by adapting the proven Invoro demo topology and release lessons without sharing application state or secrets. Build reproducible Terraform, least-privilege GitHub OIDC workflows, immutable image releases, private data services, durable shared storage, Cloudflare edge controls, rollback, and controlled shutdown/start. This plan begins only after the security/deployment plan closes all P0/P1 gates.

## Required Precondition

`docs/plans/crawlerai-security-remediation-and-deployment-fix-plan.md` must be complete through its AWS-entry gate:

- all P0/P1 findings closed with focused tests;
- production container commands proven;
- fresh migration and create-only admin bootstrap proven;
- `DATABASE_URL` component composition proven;
- MCP remains loopback-only unless per-client hosted authentication exists;
- backend/frontend images pass the agreed High/Critical scanner policy.

If any condition fails, keep this plan **BLOCKED**. Do not work around an application defect in Terraform.

## Architecture Decision

Recommended path: reuse account-wide bootstrap primitives and Cloudflare patterns, but create a separate `crawlerai-demo` application stack. Validate it beside Invoro, cut DNS, then retire Invoro deliberately.

```text
GitHub Actions OIDC
        |
        v
AWS deploy role --> ECR immutable SHA images
                         |
Cloudflare --> HTTPS ALB +--> ECS frontend
                         +--> ECS API --> RDS PostgreSQL
                                      --> ElastiCache Redis/TLS
                         +--> ECS worker --> EFS artifacts/cookies
                         +--> one-off migration/bootstrap task
                         +--> scheduled cleanup task
```

- Two Availability Zones.
- Public ALB. Public ECS subnets with assigned public IPs for crawler egress; no NAT gateway in the demo topology.
- Private RDS, Redis, and EFS data subnets/security groups.
- Cloudflare is the edge. Restrict ALB 443 ingress to current Cloudflare IPv4/IPv6 ranges after direct-origin validation.
- API container port: `8001`.
- Frontend container, target-group, and health-check port: `8080`.
- MCP is not an ALB/ECS service for first release. Users run stdio/loopback MCP with their own API key.
- One API service and one frontend service. Worker concurrency scales by ECS task count using the verified pool contract.
- Prefer an EventBridge scheduled ECS cleanup task over an always-on Celery Beat service for demo cost and single-leader safety. If Beat remains, run exactly one service and alarm on duplicates/missed schedules.

## Reuse Boundary

### Safe to reuse after inventory

- AWS account and selected region.
- GitHub OIDC provider.
- S3 Terraform state bucket.
- Cloudflare zone and edge policy pattern.
- ACM certificate only if SAN validation covers the final CrawlerAI API and frontend hosts.
- Existing tagging, budget, and log-retention conventions.

### Must be new or uniquely scoped

- Terraform backend key: `crawlerai/demo/terraform.tfstate`.
- ECR repositories: `crawlerai/backend`, `crawlerai/frontend`.
- ECS cluster/services/task definitions, IAM task roles, log groups, target groups.
- RDS database or schema/credential boundary, Redis replication group/credentials, EFS access points.
- CrawlerAI application secret bundle and provider secret references.
- Cloudflare host records and application-specific rate/cache rules.

### Never do

- Never use `invoro/demo/terraform.tfstate` for CrawlerAI.
- Never rename Invoro resources in place and apply without import/moved-block review.
- Never copy secret values merely because variable names match.
- Never pass the AWS managed policy ARN `arn:aws:iam::aws:policy/AdministratorAccess` as `role-to-assume`. GitHub needs a role ARN: `arn:aws:iam::<account-id>:role/<role-name>`.
- Never expose Redis, RDS, EFS, ECS management ports, or unauthenticated MCP publicly.

## Environment Migration Matrix

Do **not** copy `.env` wholesale. Treat it as a key-name checklist only.

| Category | Examples | Action |
| --- | --- | --- |
| Reuse same non-secret value | `AWS_ACCOUNT_ID`, `AWS_REGION`, `TF_STATE_BUCKET` | Reuse after inventory and ownership check. |
| Reuse only after validation | `ACM_CERTIFICATE_ARN`, Cloudflare zone, chosen hostnames | Confirm certificate SANs and intentional DNS cutover. |
| Same key, new unique value | JWT signing secret, encryption key, admin password, DB/Redis credentials, metrics token, API keys | Generate for CrawlerAI; store in Secrets Manager/GitHub environment as appropriate. Never reuse Invoro values. |
| Rename/map | `NEXT_PUBLIC_API_BASE_URL` → `VITE_API_BASE_URL`; `INVORO_*` → `CRAWLERAI_*` | Use CrawlerAI-native names. Keep build-time public values separate from runtime secrets. |
| Translate | Invoro PostgreSQL components → CrawlerAI centralized URL builder or complete `DATABASE_URL` | URL-encode credentials; do not concatenate in shell/workflow code. |
| Select deliberately | provider keys: Bright Data, Firecrawl, Gemini, Hugging Face, Logfire, OpenRouter, SerpAPI, Zyte | Add only enabled providers. Rotate or scope before reuse. Inject only into services that need each provider. |
| Do not copy | local URLs, `APP_ENV=development`, debug flags, local ports, placeholder values | Define production-safe values in Terraform/task definitions. |

Fresh-database rule: migration applies schema first; a one-off create-only bootstrap consumes a temporary admin credential once; steady-state API tasks run with bootstrap disabled. Remove the temporary admin password from the steady-state secret after first successful login/rotation.

## Terraform Outputs and Where They Appear

Expose only non-sensitive outputs:

- ALB DNS name and Cloudflare CNAME target;
- frontend/API hostnames;
- ECS cluster and service names;
- deploy role ARN and task-role ARNs;
- ECR repository URLs;
- RDS identifier, Redis endpoint, EFS ID/access-point IDs;
- application secret ARN, never secret contents;
- log group names and operational workflow names.

The provision workflow must render these in the GitHub Actions job summary after successful `apply`. Terraform plan values shown as `(known after apply)` are normal. Also retain the Terraform output JSON as a short-lived workflow artifact with secret outputs filtered.

## Acceptance Criteria

- [ ] CrawlerAI uses a dedicated Terraform state key and has a documented/import-safe relationship to any reused shared resources.
- [ ] GitHub OIDC roles trust the CrawlerAI repository/environment and use least-privilege bootstrap/deploy policies.
- [ ] Backend and frontend images are immutable, SHA-tagged, digest-resolved, SBOM-produced, and scan-gated.
- [ ] Deploy compares the requested SHA with the currently deployed release, reuses and rechecks the prior immutable image digest and rollback mapping for each unchanged component, and skips its migration or service rollout.
- [ ] RDS, Redis, and EFS are private and encrypted; Redis requires TLS/auth; no public data-service ingress exists.
- [ ] API, worker, migration, and scheduler receive only the secrets and IAM permissions they need.
- [ ] Migration/bootstrap completes before service rollout; failed migration prevents deploy.
- [ ] ALB liveness and deploy readiness are distinct; deploy waits for stable services and executes authenticated smoke checks.
- [ ] Changed services deploy and reach stability sequentially; any waiter failure prints service state, stopped/running task details, recent ECS events, and relevant container logs.
- [ ] Cloudflare uses Full (strict), proxies both hosts, preserves streaming/WebSocket behavior, and prevents direct-origin bypass.
- [ ] Rollback returns services to prior task-definition revisions without changing data resources.
- [ ] Stop/start preserves RDS/EFS/data and has a documented Redis/cache expectation.
- [ ] Restore drill, rollback drill, alarms, budget, log retention, and owner runbook are verified.
- [ ] Focused Terraform, image, workflow, and smoke checks exit 0.

## Do Not Touch

- `backend/app/extraction/**` — infrastructure must not rewrite extraction behavior.
- Public API/MCP contracts — only configuration and deployment wiring allowed; contract changes belong in the security plan.
- Invoro Terraform state/resources — no mutation without a separately reviewed migration/import manifest.
- `.env` files — never commit or bulk-copy them.
- Current extraction-accuracy plan — separate active work.

## Proposed File Ownership

Extend existing owners when found. Create only after grep and `docs/CODEBASE_MAP.md` confirmation.

```text
infra/aws/
  backend.tf
  providers.tf
  variables.tf
  locals.tf
  network.tf
  security_groups.tf
  iam.tf
  ecr.tf
  data.tf
  storage.tf
  secrets.tf
  ecs.tf
  alb.tf
  scheduler.tf
  observability.tf
  outputs.tf
  demo.tfvars.example
  scripts/
    release.ps1 or release.sh
    wait-for-scan.*
    smoke.*
    control.*
.github/workflows/
  aws-provision.yml
  aws-deploy.yml
  aws-control.yml
  aws-destroy.yml
frontend/Dockerfile
```

Do not copy Invoro files blindly. Port behavior and resource contracts, then rename variables/resources and delete unused Invoro assumptions.

## Slices

### Slice 0: Inventory Existing AWS and Choose Reuse Mode

**Status:** TODO
**Files:** `docs/audits/crawlerai-aws-inventory-2026-08-24.md`, plan notes, owner runbook
**What:** Read-only inventory the account, region, OIDC provider, roles/trust policies, S3 state bucket, ACM SANs, Route/Cloudflare ownership, VPCs, ALBs, ECR, ECS, RDS, Redis, EFS, Secrets Manager, CloudWatch, budgets, and service-linked roles. Confirm the GitHub repository owner/name and environment. Choose one mode:

1. **Parallel cutover (recommended):** new app stack, validate, DNS switch, retire Invoro later.
2. **Physical-resource migration:** explicit import inventory, state backup, `moved` blocks, and a zero-unexpected-destroy plan. This mode requires separate human approval before apply.

Record cost estimate and quota headroom. Confirm or precreate required RDS/ElastiCache/ECS service-linked roles. ElastiCache `408 InvalidCredentialsException` can be transient during service-linked-role readiness; use a bounded retry only after role, account, and region checks pass.
**Verify:** Inventory names every reused/new resource, owner, state address, data classification, and destroy behavior. No write occurs.

### Slice 1: Freeze Names, Hosts, State, and Variables

**Status:** TODO
**Files:** `infra/aws/backend.tf`, `providers.tf`, `variables.tf`, `locals.tf`, `demo.tfvars.example`, `.env.example`, runbook
**What:** Set `crawlerai-demo` naming, mandatory tags, approved account/region checks, Terraform/provider versions, and S3 backend with `use_lockfile = true`. Use backend key `crawlerai/demo/terraform.tfstate`. Define `CRAWLERAI_FRONTEND_HOST` and `CRAWLERAI_API_HOST`. Validate sensitive variables and prevent them from becoming outputs. Use CrawlerAI settings names and `VITE_API_BASE_URL`. Keep runtime tunables in backend config, not Terraform templates or service code.
**Verify:** `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`, variable negative tests, and state-key grep prove no Invoro key/name leak.

### Slice 2: Build Production Images and Runtime Contracts

**Status:** TODO
**Files:** hardened `backend/Dockerfile`, `frontend/Dockerfile`, frontend server config, `.dockerignore` files, health scripts, targeted container tests
**What:** Use digest-pinned multi-stage images. Backend installs frozen production dependencies and Patchright browser runtime, runs non-root, and exposes 8001. Frontend builds with VitePlus and serves static assets non-root on the frozen port with SPA fallback, immutable hashed-asset caching, no-cache HTML, security headers, and a runtime health endpoint. Produce separate commands for API, worker, migration/bootstrap, and scheduled cleanup using `.venv/bin/*`. Do not bake credentials or environment files into layers.
**Verify:** Reproducible builds; non-root inspection; secret-pattern layer scan; backend live/ready checks; frontend deep-link refresh; one worker task; one migration/bootstrap cycle.

### Slice 3: Create Bootstrap IAM and Correct GitHub OIDC Trust

**Status:** TODO
**Files:** `infra/aws/iam.tf`, bootstrap policy/trust docs, `.github/workflows/aws-provision.yml`
**What:** Reuse or create the account GitHub OIDC provider. Create a narrowly scoped bootstrap role for Terraform and a deploy role for release/control. Trust only the exact `repo:<owner>/CrawlerAI:environment:aws-demo` subject and approved audience. Do not copy an Invoro-only trust subject. Separate ECS execution roles from app task roles (API, worker, migration, scheduler). Default task roles to no AWS API access; add only required secret/log/storage calls. Pin GitHub Actions by immutable SHA using Node 24-compatible releases.
**Verify:** IAM policy simulation, trust-policy negative tests for another repo/branch/environment, OIDC dry run, and workflow permission review. `role-to-assume` values are IAM role ARNs.

### Slice 4: Create Network and Origin Controls

**Status:** TODO
**Files:** `infra/aws/network.tf`, `security_groups.tf`, `alb.tf`, variables/outputs
**What:** Create two-AZ VPC/subnets. Keep ALB public. Place RDS/Redis/EFS endpoints in private data subnets. Place ECS tasks in public egress subnets for demo crawler access without NAT. Allow ALB → frontend/API, API/worker/migration → RDS/Redis, and only required services → EFS. Give frontend no DB/Redis path. Start ALB 443 from a controlled operator CIDR for bootstrap, then restrict to current Cloudflare IPv4/IPv6 ranges after validation. Add HTTP→HTTPS redirect. Explicitly account for ECS metadata and internal reachability through application-layer connect-time SSRF enforcement; do not attach privileged task roles to crawler workers.
**Verify:** Terraform graph and reachability review show no public data-service path, no frontend-to-data path, and no unintended east-west rules. Direct origin is blocked after Cloudflare cutover.

### Slice 5: Provision Data, Storage, Secrets, and Recovery

**Status:** TODO
**Files:** `infra/aws/data.tf`, `storage.tf`, `secrets.tf`, KMS/backup configuration, runbook
**What:** Provision encrypted RDS PostgreSQL with managed master secret, deletion protection for steady state, backups/PITR, and private access. Provision encrypted ElastiCache with TLS and auth token/ACL; verify application `rediss://` behavior. Provision encrypted EFS with separate least-privilege access points for artifacts and cookie state where possible. Store application/provider secrets separately and inject only into required containers. Generate CrawlerAI-specific values. Define snapshot/final-snapshot behavior and demo expiry. Avoid broad `.env` injection into every task.
**Verify:** TLS connection tests, IAM/secret access negative tests per task role, encrypted mount tests, backup creation, and disposable restore drill.

### Slice 6: Define ECS Tasks, Services, Migration, and Scheduling

**Status:** TODO
**Files:** `infra/aws/ecs.tf`, `scheduler.tf`, task definitions, observability wiring
**What:** Define API/frontend services and worker tasks using immutable image digests. Use separate roles and secret sets. Mount EFS only where runtime needs shared artifacts/cookies. Register a one-off migration/bootstrap task and require successful exit before service rollout. API steady state sets bootstrap false. Start with one solo worker process per task; scale ECS desired count for concurrency. Implement cleanup as EventBridge scheduled one-off ECS task, or document why exactly-one Beat is retained. Configure graceful stop timeouts so browsers/subprocesses close before SIGKILL.
**Verify:** Task-definition inspection, fresh migration/bootstrap, API restart, worker job, scheduled cleanup, graceful shutdown, and cross-service secret-denial checks.

### Slice 7: Configure ALB Routing, Health, and Streaming

**Status:** TODO
**Files:** `infra/aws/alb.tf`, listener rules, target groups, output definitions
**What:** Route API host to API target group and frontend host to frontend target group. Use `/health/live` for ALB liveness. Deployment workflow separately polls `/health/ready`. Tune idle timeout for supported SSE/WebSocket/long-response behavior. Set deregistration delay and health thresholds for clean rolling deploys. Keep API docs disabled in production and metrics token-gated/non-public.
**Verify:** Host routing, HTTP redirect, liveness failure removal, readiness deploy block, SSE/WebSocket smoke, and zero cross-target routing.

### Slice 8: Implement Provision and Deploy Workflows

**Status:** TODO
**Files:** `.github/workflows/aws-provision.yml`, `aws-deploy.yml`, `infra/aws/scripts/*`
**What:** Add manual `workflow_dispatch` provision/apply and deploy workflows. Provision emits plan and requires configured environment protection before apply. Deploy accepts only a main-branch commit SHA and compares component paths with the currently deployed release, not merely the previous commit. Build and digest-resolve only changed components; reuse each unchanged component's prior immutable image digest and retain its release-to-rollback mapping. Apply the vulnerability gate to both new and reused digests. Skip migrations and service updates when their component is unchanged. Deploy changed services sequentially and wait for each to stabilize before starting the next. On waiter failure, print ECS service state, task and stop-reason details, recent service events, and relevant CloudWatch logs before failing. Merging alone does not auto-apply or deploy unless the owner later chooses that policy. Publish non-sensitive outputs, selected/reused digests, and rollback coordinates in the job summary.
**Verify:** Workflow static validation; dry-run input rejection; frontend-only SHA proves unchanged backend/API/worker images and task definitions are reused with no migration or backend rollout; safe-image pass; vulnerable-image block; failed-migration block; sequential service rollout and wait ordering; forced waiter failure emits service/task/event/log diagnostics; successful canary/smoke; rollback coordinates cover both changed and reused component digests; no plaintext Docker credential warning.

### Slice 9: Add Rollback, Control, and Destroy Workflows

**Status:** TODO
**Files:** `.github/workflows/aws-control.yml`, `aws-destroy.yml`, scripts, owner runbook
**What:** Add explicit actions for status, scale-to-zero/start, RDS stop/start where supported, log tail pointers, service rollback to prior task-definition revisions, and safe destroy. Rollback changes compute revisions only; it never rolls database schema backward automatically. Destroy requires typed stack/environment confirmation, state backup, protected-resource inventory, final-snapshot choice, and environment approval. Document Redis cache loss expectations and RDS stop time limits.
**Verify:** Controlled stop/start preserves data; rollback restores prior images; destructive workflow refuses wrong confirmation and presents exact targets before approval.

### Slice 10: Configure Cloudflare and Cut Traffic

**Status:** TODO
**Files:** Cloudflare change record/runbook, Terraform variables/outputs, smoke scripts
**What:** Create proxied frontend/API DNS records pointing to the ALB. Require SSL/TLS Full (strict), certificate/SAN match, Always Use HTTPS, API no-cache, static cache rules, request body and rate controls, and WebSocket/SSE compatibility. Allow CORS only from the exact frontend origin. After smoke succeeds, restrict ALB ingress to Cloudflare ranges and prove direct-origin bypass fails. Reduce DNS TTL before planned cutover. Keep prior Invoro records/resources intact until rollback window closes.
**Verify:** TLS chain, proxied DNS, cache headers, CORS, streaming, API-key rate controls, oversized-body rejection, and direct ALB/origin denial.

### Slice 11: Observability, Cost, Recovery, and Handoff

**Status:** TODO
**Files:** `infra/aws/observability.tf`, dashboards/alarms, owner runbook, final readiness audit
**What:** Add structured CloudWatch logs with bounded retention and redaction. Alarm on ALB 5xx/latency/unhealthy targets, ECS restarts/desired mismatch, migration failure, worker queue age/failure, RDS capacity/connections, Redis capacity/evictions/auth errors, EFS use, and missed cleanup. Add AWS Budget alerts and consistent tags. Perform deployment rollback and RDS restore drills. Record routine deploy, output lookup, DNS, scale, secret rotation, certificate renewal, incident, and teardown steps.
**Verify:** Trigger test alarms; show dashboard data; restore into a disposable target; complete rollback; owner follows the runbook without repository knowledge.

## Workflow Secrets and Variables

Use a protected GitHub environment such as `aws-demo`.

### Repository/environment variables

- `AWS_ACCOUNT_ID`
- `AWS_REGION`
- `AWS_BOOTSTRAP_ROLE_ARN`
- `AWS_DEPLOY_ROLE_ARN` after provisioning
- `TF_STATE_BUCKET`
- `ACM_CERTIFICATE_ARN`
- `CRAWLERAI_FRONTEND_HOST`
- `CRAWLERAI_API_HOST`
- `DEFAULT_ADMIN_EMAIL`
- `DEMO_EXPIRY_DATE`

### Secrets

Prefer AWS Secrets Manager for runtime secrets. GitHub should not hold application secrets unless a bootstrap flow strictly requires one. Generate and rotate:

- JWT signing secret;
- application encryption key;
- initial admin bootstrap password;
- metrics token;
- Redis auth secret;
- enabled provider/proxy credentials.

RDS master credentials remain AWS-managed. Public frontend build variables are not secrets.

## Focused Verification Matrix

```powershell
cd C:\Projects\CrawlerAI\infra\aws
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
terraform plan -var-file=demo.tfvars -out=crawlerai.tfplan
terraform show -json crawlerai.tfplan

cd C:\Projects\CrawlerAI
docker build --pull -f backend/Dockerfile -t crawlerai-backend:local backend
docker build --pull -f frontend/Dockerfile -t crawlerai-frontend:local frontend
docker inspect crawlerai-backend:local crawlerai-frontend:local

cd frontend
vp test --run app/api-access
```

Use targeted container/smoke scripts for migration, bootstrap, health, worker, frontend routing, and streaming. CI during ship-main owns the broad suite.

## Rollback and Data Safety

- Record previous API/frontend/worker task-definition revisions before update.
- Roll back services to those revisions if readiness or smoke fails.
- Never auto-downgrade Alembic schema. Forward-fix or restore a tested snapshot under an incident decision.
- Keep Invoro live until CrawlerAI cutover checks and rollback window pass.
- Back up Terraform state before imports, moved blocks, or destructive operations.
- A Terraform plan with any unexpected RDS, Redis, EFS, secret, or state-bucket destroy is an automatic stop.

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` — infrastructure, scripts, workflow, and frontend-container ownership.
- [ ] `docs/backend-architecture.md` — AWS runtime, worker scheduling, storage, health, secrets.
- [ ] `docs/frontend-architecture.md` — static production container, host routing, runtime API URL contract.
- [ ] `docs/INVARIANTS.md` — deployment config, durable storage, MCP non-exposure, SSRF/network boundary.
- [ ] `docs/INVARIANTS.md` — infrastructure/state ownership and release gates.
- [ ] `docs/plans/CRAWLERAI_AWS_OWNER_RUNBOOK.md` or canonical runbook owner — provision, deploy, output lookup, control, rollback, restore, destroy.

## Notes

- Terraform `(known after apply)` output is expected during plan. Actual values appear after successful apply and must be summarized in the workflow job summary.
- The prior ElastiCache 408/`InvalidCredentialsException` lesson is handled by service-linked-role preflight and bounded retry, not manual cache creation.
- GitHub action pins must remain Node 24-compatible. Do not set the insecure Node 20 override.
- Use the ECR credential helper and temporary Docker config to avoid unencrypted runner credential storage.
- No hosted public MCP service exists in this first architecture. The existing UI documents local MCP plus the public REST API.
- Direct physical reuse of Invoro RDS/Redis/EFS is not the default. If chosen, stop this plan and write the exact import/data-migration plan before any apply.
- Invoro incident finding: a frontend-only SHA rebuilt and redeployed unchanged backend/API/worker components; the ECS waiter then failed even though frontend was healthy. Release change detection must use the currently deployed release as its baseline, preserve immutable digest and rollback mappings for unchanged components, recheck reused digests against the vulnerability policy, skip their migrations/rollouts, update and wait one changed service at a time, and emit service/task/event/log diagnostics before any waiter failure exits.

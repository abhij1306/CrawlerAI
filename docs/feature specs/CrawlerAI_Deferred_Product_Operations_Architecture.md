# CrawlerAI Deferred Product, Operations, Governance, and Enterprise Architecture

**Status:** Deferred architecture and decision register  
**Purpose:** Preserve important non-extraction requirements and gaps for later development without mixing them into the extraction-first architecture.  
**Dependency:** This document assumes the crawl and extraction engine defined in `CrawlerAI_Extraction_First_Architecture.md`.  
**Legacy decision:** No legacy PHP script migration or import is planned.

---

## 1. Why This Document Exists

The immediate development focus is CrawlerAI’s acquisition and extraction correctness.

However, a complete self-service platform eventually requires more than an extraction engine. It also requires:

- user-facing onboarding;
- feed-contract authoring;
- multi-client ownership;
- credentials and compliance;
- escalation and queue operations;
- portfolio monitoring;
- client risk policies;
- communication;
- service levels;
- cost governance;
- training;
- product metrics.

These concerns are credible and important, but they should not distort or delay the extraction architecture.

This document records them as a separate future architecture so they are not lost.

---

## 2. Deferred Product Goal

The eventual product goal is:

> Feedonomics feed-operations users can define, onboard, launch, monitor, and maintain standard commerce and jobs crawls without depending on a dedicated crawl team, while genuinely exceptional cases are routed to an explicit engineering function.

That outcome requires a product and operating model around the extraction engine.

It must not be assumed merely because the backend can extract data.

---

## 3. Explicit Exclusions from the Extraction-First Phase

The extraction-first phase does not need to finalize:

- end-to-end self-service domain onboarding;
- portfolio and bulk operations;
- client-facing feed-contract editing;
- organization and tenant ownership;
- credential storage;
- legal and access-policy approval;
- enterprise audit logs;
- queue priorities and SLAs;
- client communications;
- leadership KPI dashboards;
- training and certification;
- billing and cost allocation;
- full LLM-assisted onboarding;
- complex no-code browser-interaction authoring.

The extraction architecture must expose clean APIs and evidence so these can be added later.

---

## 4. Future Product Planes

A complete platform will add a Product and Operations Plane above the extraction data and control planes.

Major surfaces:

- Feed Contract Studio;
- Domain Onboarding;
- Template Confirmation;
- Escalation Console;
- Portfolio Operations;
- Delivery and Feedonomics Outcomes;
- Client Risk Policy;
- Credential and Access Management;
- Compliance Review;
- Engineering Escalation;
- Program Analytics.

---

## 5. Multi-Tenant and Shared-Domain Ownership

A future architecture must define:

- organization;
- workspace;
- client;
- feed;
- domain;
- template;
- shared platform capability;
- ownership and permissions.

Critical questions:

- Can two clients crawl the same domain with different feed contracts?
- Are acquisition sessions shared or isolated?
- Are politeness and request budgets shared per domain?
- Can one client’s confirmed extraction strategy influence another client?
- Which platform capabilities are globally shared?
- How is client-specific evidence isolated?
- Who owns a domain-template configuration?

Recommended principle:

> Platform capabilities may be shared globally, but client contracts, credentials, evidence, publication policy, and approvals must remain tenant-scoped unless explicitly shared.

---

## 6. Release and Change Governance

The extraction architecture defines a runtime release bundle.

The future product must add governance around:

- who may create a release;
- who may approve it;
- who may activate it;
- separation of duties;
- emergency rollback;
- change reason;
- audit trail;
- scheduled rollout;
- notification of affected feeds.

Platform-level changes require:

- affected-domain inventory;
- regression testing;
- canary tenants;
- staged percentage rollout;
- automatic rollback rules;
- global incident ownership.

Threshold loosening must be:

- permission-controlled;
- logged;
- reversible;
- visible in risk reporting.

---

## 7. New-Domain Onboarding Product

A later onboarding workflow should cover:

1. define the feed contract;
2. provide seed URLs, sitemap, or known endpoints;
3. run automated template discovery;
4. review representative samples;
5. resolve missing or conflicting fields;
6. validate sample records;
7. configure publication and stale-data policy;
8. launch in a controlled pre-production state;
9. approve production activation.

### 7.1 New domain with no baseline

A new domain has no last-known-good output.

The future product must define:

- whether unconfirmed critical fields block launch;
- whether optional fields may be omitted;
- the minimum evidence required to activate;
- who may approve uncertain fields;
- how many representative samples are required.

Recommended principle:

> A new domain does not publish critical commercial fields until its templates and critical field semantics are confirmed.

---

## 8. Feed Contract Studio

The eventual UI should let authorized users define:

- commerce or jobs surface;
- row granularity;
- core fields;
- typed custom fields;
- entity scope;
- requiredness;
- criticality;
- output mapping;
- allowed values;
- stale-data policy;
- suppression behavior;
- client risk profile.

Custom fields should use controlled types rather than arbitrary keys.

---

## 9. Client Risk Profile

Publication and incident behavior should not be configured independently for every event.

A client risk profile may define:

- tolerance for stale data;
- tolerance for missing optional fields;
- whether zero records are preferable to uncertain prices;
- critical fields;
- maximum stale age;
- fail-open versus fail-closed behavior;
- escalation urgency;
- delivery windows.

Example profiles:

- conservative commercial;
- availability-sensitive;
- content-tolerant;
- strict completeness;
- custom.

The risk profile should provide defaults, not prevent feed-specific overrides.

---

## 10. Operator Escalation Console

A future console should translate extraction evidence into a decision.

Default actions should be deliberately limited:

1. accept recommended fix;
2. restore or retain last known good;
3. escalate to engineering.

Advanced actions may exist behind role or permission gates.

Each escalation should show:

- business impact;
- affected records and fields;
- current behavior;
- previous accepted behavior where available;
- proposed behavior;
- plain-language risk;
- screenshots and highlighted evidence;
- expected effect of accept and reject;
- recommendation;
- deadline or SLA.

The console must not assume a non-specialist can choose a variant join from raw JSON paths.

---

## 11. Queue, SLA, and Alerting Model

A future operating model must define:

- alert channels;
- severity;
- owner;
- aging;
- escalation path;
- response target;
- resolution target;
- status transitions;
- after-hours policy.

Possible severities:

- P0 feed-wide critical data corruption;
- P1 critical field or large template failure;
- P2 partial degradation;
- P3 optional-field or low-impact issue.

Tier C engineering escalation requires a real SLA. “Escalate to engineering” is not sufficient without ownership and response expectations.

---

## 12. Portfolio and Bulk Operations

Feed Operations Users may manage many domains.

Required future capabilities:

- cross-domain health view;
- queue sorted by impact;
- bulk acknowledgement;
- bulk application of a proven repair pattern where safe;
- platform incident grouping;
- affected-client view;
- stale-feed view;
- cost and browser-usage view;
- rollout and rollback across selected feeds.

The product should distinguish:

- one-domain defect;
- one-template defect;
- platform-wide regression;
- Feedonomics delivery incident;
- credential or access failure.

---

## 13. Secrets and Credential Architecture

Future authenticated acquisition requires:

- encrypted secret storage;
- tenant and feed scope;
- role-based access;
- secret references rather than plaintext in contracts;
- rotation;
- expiration;
- access audit;
- redacted diagnostics;
- environment separation;
- incident revocation.

Non-technical users should never paste credentials into unstructured notes.

Supported credential types may include:

- username and password;
- API key;
- cookie or token;
- OAuth grant;
- client certificate;
- secret header.

---

## 14. Compliance, Legal, and Access Policy

A named workflow is required for:

- robots policy;
- terms-of-service concerns;
- client authorization;
- authenticated access;
- rate limits;
- personally identifiable information;
- protected or adversarial sources;
- geographic restrictions;
- data-use restrictions.

Possible owner:

- compliance role;
- platform administrator with legal escalation;
- dedicated access-review function.

The extraction engine may classify `access_policy_review`, but the product must own the decision and audit trail.

---

## 15. Data Retention, Privacy, and PII

The extraction architecture defines technical retention tiers. The future platform must define policy.

Policy dimensions:

- artifact type;
- tenant;
- domain;
- data classification;
- retention duration;
- redaction;
- deletion request;
- legal hold;
- encryption;
- region;
- access audit.

High-risk captured content may include:

- recruiter contact details;
- user-generated reviews;
- account data;
- session tokens;
- embedded personal data;
- screenshots.

Rejected candidate evidence should not be retained indefinitely by default.

---

## 16. Pending-Review and Stale-Data Policy

For post-launch regressions, the product must decide whether to:

- serve last-known-good;
- publish without an optional field;
- suppress affected records;
- pause an affected template;
- pause the full feed.

For first onboarding, no last-known-good exists.

The future product must distinguish:

- initial unconfirmed state;
- post-launch regression;
- expired stale state;
- Feedonomics rejection;
- access failure.

This policy should be derived from the client risk profile and field criticality.

---

## 17. Operator Error Recovery

The system needs lightweight recovery for human mistakes.

Required capabilities:

- undo last approval;
- preview before activation;
- grace period for selected changes;
- dual approval for high-risk fields;
- full release rollback;
- audit history.

Operator undo is not the same as system rollback and should be easier for recent actions.

---

## 18. Engineering Escalation and Return Path

An engineering escalation must include:

- classified problem;
- capture references;
- affected templates and fields;
- attempted repairs;
- business impact;
- reproducible test case.

The engineer’s resolution must return through a defined path:

1. implement or configure capability;
2. add regression fixtures;
3. create candidate extraction release;
4. replay and canary;
5. document operator-visible behavior;
6. transfer ownership back to operations.

Reusable engineering fixes should become:

- platform capability;
- deterministic collector;
- validator;
- supported interaction primitive;
- semantic guard.

---

## 19. LLM-Assisted Product Experience

LLM capabilities may later help:

- explain extraction evidence;
- label fields;
- summarize conflicts;
- generate operator-facing risk descriptions;
- recommend which sample to inspect;
- answer questions about a template.

The product should not initially depend on autonomous executable-rule generation.

LLM deployment decisions include:

- approved models;
- data privacy;
- prompt and response retention;
- cost limits;
- caching;
- human review;
- evaluation corpus;
- failure monitoring.

---

## 20. Client Communication

A future product may need to communicate:

- delayed or degraded feed;
- stale-data use;
- suppressed fields;
- access failure;
- resolved incident;
- required client action.

Decisions:

- whether communication is automatic;
- whether Feed Operations approves messages;
- channels;
- templates;
- client-visible status pages;
- disclosure of technical details.

---

## 21. Program Metrics and Business KPIs

To validate the self-service goal, track:

- percentage of domains by support tier;
- time to onboard;
- time to first valid feed;
- extraction-engineering escalation rate;
- escalation age;
- mean time to repair;
- domains independent of specialist support;
- platform incident frequency;
- false auto-repair rate;
- rollback rate;
- browser and LLM cost;
- Feedonomics rejection rate;
- operator override rate;
- client-impact minutes.

These metrics determine whether the product is actually reducing crawl-team dependency.

---

## 22. Cost, Capacity, and Commercial Controls

Future controls should include:

- per-tenant crawl quotas;
- browser budgets;
- interaction budgets;
- LLM budgets;
- artifact-storage budgets;
- replay budgets;
- live-validation frequency;
- rate limits;
- cost attribution;
- high-cost domain alerts.

The UI should expose expected cost class before activation.

---

## 23. Training and Operator Readiness

A production launch requires:

- guided walkthroughs;
- failure-state examples;
- field-semantic examples;
- current versus compare-at price training;
- variant-binding examples;
- safe rollback practice;
- role certification where appropriate.

The product should minimize training needs but cannot assume zero learning.

---

## 24. Rollout and Quality Acceptance

There is no legacy PHP import or migration path.

When existing domains are eventually moved to CrawlerAI, they should be re-onboarded through the new architecture from first principles.

Future rollout should define:

- manually verified representative sample set;
- expected critical field accuracy;
- variant integrity checks;
- Feedonomics acceptance;
- observation period;
- rollback exercise;
- explicit launch approval.

Existing outputs may be used as comparison evidence, but no legacy script or imperative logic is imported into the architecture.

---

## 25. Deferred Data-Model Additions

Likely future entities:

- organization;
- workspace;
- client;
- feed;
- domain ownership;
- credential reference;
- risk profile;
- escalation;
- SLA policy;
- approval;
- notification;
- access review;
- compliance decision;
- operator action;
- client communication;
- cost ledger.

These should be added only after extraction contracts and runtime releases are stable.

---

## 26. Priority Order for Later Development

### P0 — required before broad self-service launch

- multi-tenant ownership;
- credential handling;
- legal and access review;
- client risk profile;
- new-domain no-baseline publication policy;
- escalation queue and SLA;
- release approval governance;
- data-retention and PII policy.

### P1 — required for scaled operations

- portfolio and bulk tooling;
- operator decision framing;
- engineering return workflow;
- alerts and notifications;
- operator undo;
- Feedonomics outcome integration;
- cost governance;
- program metrics.

### P2 — optimization and maturity

- client-facing status communication;
- advanced LLM assistance;
- generalized platform reuse administration;
- training and certification;
- leadership dashboards;
- automated bulk repair patterns.

---

## 27. Critical Decisions to Preserve for Later

1. Tenant isolation and shared-domain policy.
2. Credential storage and access model.
3. Compliance owner and approval workflow.
4. New-domain critical-field launch policy.
5. Client risk-profile model.
6. Queue severity and SLA.
7. Operator permissions and dual approval.
8. Retention and PII policy.
9. Portfolio-scale workflow.
10. Feedonomics feedback ownership.
11. Engineering escalation and return path.
12. LLM privacy and operating policy.
13. Cost allocation and budgets.
14. Client communication behavior.
15. Self-service success metrics.

---

## 28. Relationship to the Extraction Architecture

The future product must consume extraction outputs through stable contracts:

- runtime release;
- template;
- acquisition assessment;
- field evidence;
- entity decisions;
- trust state;
- diagnostic reason codes;
- repair candidate;
- replay comparison;
- cost observations.

The extraction system should not embed:

- tenant-specific workflow;
- queue ownership;
- notification logic;
- credential UI;
- compliance decisions;
- client messaging.

This separation allows the extraction engine to be simplified and stabilized before the broader product layer is built.

# GoFindMe — Data Handling & Privacy Statement

This one-page statement summarizes what GoFindMe stores, where it lives, and how it
is protected. It is written for procurement, privacy, and security reviewers. For
the full technical treatment see [SECURITY.md](SECURITY.md) and
[DEPLOYMENT.md](DEPLOYMENT.md).

## Deployment & data residency

GoFindMe is **self-hosted and single-tenant**. It runs entirely on infrastructure the
operator controls — a desktop, an on-premises server, a private VPS, or an
air-gapped host. There is no vendor cloud, no telemetry, and no phone-home. All data
resides in one SQLite database on the operator's machine; **data residency is
wherever the operator runs it.**

## What is stored

| Category | Examples | Where |
|---|---|---|
| Case records | Case reference, title, subject, examiner, legal authority, status, summary | `cases` table |
| Findings | Normalized results from tools/providers, source, timestamp, capped raw payload | `findings` table (scoped by case) |
| Investigator data | Identities, accounts, timeline events, notes | scoped tables |
| Provider API keys | Third-party service keys entered by the operator | `vault_secrets` (encrypted) |
| Audit trail | Who/what/when for security-relevant actions | `audit_chain` (hash-linked) |
| Credentials | Owner username + password **hash** (Argon2id) | `app_user` table |

GoFindMe does **not** collect analytics, usage telemetry, or any data about the
operator. It stores only what the operator enters or what an investigation returns.

## How it is protected

- **API keys** are encrypted at rest with AES-256-GCM under a key derived from an
  operator passphrase (PBKDF2-HMAC-SHA256, 200k iterations). The passphrase is never
  stored; the vault auto-locks when idle.
- **Passwords** are stored only as Argon2id hashes, never in plaintext.
- **Audit trail** is a tamper-evident SHA-256 hash chain; any edit or deletion of a
  historical entry is detectable and pinpointed by the built-in verifier and is
  attested in every generated report.
- **Access** requires authentication; the server binds to loopback by default and is
  intended to be exposed only over a private network or TLS reverse proxy.
- **Transport** security (TLS) is provided by the operator's reverse proxy or
  Tailscale in networked deployments; loopback/desktop use is local-only.

## PII posture & operator responsibilities

Investigation data may contain personal information about subjects. GoFindMe is a
tool; the **operator is the data controller** and is responsible for lawful basis,
authorization, retention, minimization, and subject-rights handling under applicable
law. GoFindMe supports this with per-case scoping, export (JSON/Markdown/PDF), and
case deletion (which unlinks scoped evidence).

## Retention & disposal

Retention is operator-defined. Data persists in the SQLite database until the
operator deletes a case or removes the database file. To dispose of all data,
stop the service and securely delete the database file and its `-wal`/`-shm`
sidecars. Back up by copying those files while the service is stopped.

## Known limitations (disclosed)

- Only the API-key vault is encrypted at rest today; case and audit data rely on
  operating-system / full-disk encryption. Database-level encryption (SQLCipher) is
  on the roadmap.
- The audit chain is tamper-**evident**, not tamper-**proof**; external tip-anchoring
  is on the roadmap. See SECURITY.md for detail.
- The current release is single-user; multi-user RBAC and MFA are on the roadmap.

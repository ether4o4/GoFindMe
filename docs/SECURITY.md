# GoFindMe — Security Whitepaper

**Document class:** Procurement / technical due-diligence reference
**Product:** GoFindMe — self-hosted OSINT / DFIR investigation console
**Applies to:** Application version 1.0.0
**Audience:** Security architects, procurement and compliance reviewers in law enforcement, intelligence, fraud/AML, and private-sector security teams

> **Scope and honesty note.** Every control described here is grounded in the current source tree. Where a capability is *planned but not yet implemented*, it is labeled as roadmap and is **not** counted as a present control. GoFindMe is currently a **single-user, single-tenant, operator-controlled** application; it is **not** a multi-user RBAC platform today. No claim of certification or formal accreditation is made anywhere in this document. Compliance references use the language "supports" / "aligns with," never "certified" or "compliant."

---

## 1. Overview & Threat Model

GoFindMe is a self-hosted application that an investigator (the "operator") runs on infrastructure they control. It aggregates open-source intelligence by (a) dispatching an allowlisted set of local OSINT command-line tools and (b) querying third-party provider APIs server-side, then storing findings, case records, and a tamper-evident audit trail in a single local SQLite database.

### 1.1 Deployment assumptions

- **Single tenant, single operator.** One owner account is provisioned on first run. There is no built-in multi-user directory, no role separation, and no tenancy boundary inside the process. Isolation between investigators, teams, or agencies is achieved by running **separate instances**.
- **Operator-controlled host.** The security posture assumes the host OS, disk, and network are under the customer's administrative control. GoFindMe hardens the application layer; it relies on the operator for host hardening (non-root service account, full-disk encryption, patching, backups).
- **Loopback by default.** Out of the box the server binds `127.0.0.1` and is reachable only from the local machine. Any wider exposure is an explicit, opt-in configuration change (Section 8).

### 1.2 Protected assets

| Asset | Where it lives | Primary protection |
|-------|----------------|--------------------|
| Provider API keys | `vault_secrets` table (SQLite) | AES-256-GCM sealed under a passphrase-derived key; never written to logs or process environment |
| Case evidence & findings | SQLite tables (`cases`, `findings`, `timeline_events`, `accounts`, `notes`, `identity_items`) | Application authentication; host filesystem controls; audit trail |
| Audit trail / chain of custody | `audit_chain` table (SQLite) | Append-only SHA-256 hash chain with verification and pinpointing |
| Login credential | `app_user.pw_hash` | Argon2id hash (PBKDF2 fallback); never stored in plaintext |
| Live session token | Process memory only | Random opaque token; not persisted; invalidated on restart |

### 1.3 Threats considered

- **Theft of the database file at rest.** A stolen `gofindme.db` yields **no live session tokens** (memory-only) and **no usable API keys** without the vault passphrase (which is never stored). Case data and audit rows in the DB are, however, readable unless the operator has enabled OS/disk encryption — see Section 7 and the roadmap.
- **Command / argument injection through investigation targets.** Every user-supplied target passes strict anchored validators and is executed only as a discrete `argv` element with **no shell** (Section 5).
- **Server-Side Request Forgery via provider lookups.** Provider hosts are hardcoded; the target only ever lands in a URL path/query (URL-encoded by the HTTP client), private/reserved IPs are refused, and redirects are not followed (Section 2, Section 5).
- **Credential brute force.** Login is rate-limited and passwords are hashed with a memory-hard KDF (Section 3).
- **Tampering with the evidence trail.** Piecemeal edits or deletions of audit rows break the hash chain and are detected and pinpointed by verification (Section 6, with an honest limitation on wholesale rewrite).

### 1.4 Explicit non-goals / out of scope (today)

- Multi-user access control, per-role permissions, and tenant isolation (roadmap — Section 10).
- Cryptographic encryption of the **whole** database at rest (only vault secrets are encrypted; roadmap covers SQLCipher).
- Protection against a fully privileged host compromise (root on the box can read process memory, including an unlocked vault passphrase).
- Multi-factor authentication and external identity federation (roadmap).

---

## 2. Architecture & Data Flow

GoFindMe is a single FastAPI (ASGI) process. It serves both the JSON API and the static dashboard **from the same origin**, so there is no cross-origin request surface and CORS is not enabled.

```
 phone ─┐
 laptop ─┼──▶  FastAPI process (uvicorn, single origin, no CORS)
 desktop ┘         │
                   ├─ auth & session      → Argon2id + in-memory bearer tokens
                   ├─ tool dispatcher      → asyncio.create_subprocess_exec (argv list, never a shell)
                   ├─ provider layer       → httpx, server-side, host-pinned, redirects off
                   ├─ encrypted vault      → PBKDF2-HMAC-SHA256 (200k) + AES-256-GCM
                   ├─ in-process job queue → asyncio workers; live output over SSE
                   └─ audit chain          → append-only SHA-256 hash chain
                   │
                   ▼
              SQLite (WAL mode) — single local source of truth
```

**Key architectural properties:**

- **Same-origin, no CORS.** The dashboard and API share one origin; the middleware sets a strict Content-Security-Policy and hardening headers on every response (Section 8).
- **In-process job queue.** Concurrency is provided by a bounded pool of `asyncio` worker tasks (default 4, configurable) — no external broker (no Celery/Redis), reducing the network attack surface and operational footprint. Heavy tools carry an additional per-tool sub-cap. Jobs left `running`/`queued` when the process dies are reconciled to `error` on the next start.
- **Server-side outbound lookups.** All provider API calls originate from the server process using `httpx`, which honors an optional CA bundle and proxy from configuration. This both removes the browser CORS wall and keeps API keys off the client entirely.
- **One datastore.** State is a single SQLite database in WAL mode; all devices that can reach the instance read one consistent source of truth.

---

## 3. Authentication & Session Management

> **Present state: single-user authentication.** Exactly one owner account exists (its row is pinned to `id = 1` in the schema). There is no role model, group, or second account. Multi-user auth and RBAC are on the roadmap (Section 10) and are **not** present today.

### 3.1 Credential storage

- Passwords are hashed with **Argon2id** via `passlib`. If the Argon2 backend is unavailable in a given build (for example a constrained mobile packaging), the code transparently falls back to **PBKDF2-SHA256**; existing hashes remain verifiable because their scheme identifier is retained.
- A minimum password length of 8 characters is enforced at account creation. Password plaintext is never stored or logged.

### 3.2 Sessions and tokens

- On successful login the server issues an **opaque, random bearer token** (`secrets.token_urlsafe(32)`) and stores it **only in process memory** (a `token → expiry` map). Tokens are **never written to the database**.
- Consequence: a stolen database yields **no live sessions**, and a process restart invalidates all sessions.
- Token lifetime is configurable (`GOFINDME_TOKEN_TTL_DAYS`, default 7 days); expired tokens are rejected and evicted on use.
- Tokens are accepted either via the `Authorization: Bearer …` header or via a cookie. The cookie form exists so that browser `EventSource`/SSE streams can authenticate without placing the token in a URL.

### 3.3 Cookie flags

The session cookie (`gfm_token`) is set with:

| Flag | Value | Effect |
|------|-------|--------|
| `HttpOnly` | on | Not readable from JavaScript, reducing token theft via XSS |
| `SameSite` | `strict` | Not sent on cross-site requests, mitigating CSRF |
| `Secure` | set when the request scheme is HTTPS | Cookie withheld over plaintext HTTP |
| `Path` | `/` | Scoped to the app |
| `Max-Age` | token TTL | Bounded lifetime |

> **Deployment note on `Secure`.** The `Secure` flag is applied when the request is seen as HTTPS. Behind a TLS-terminating reverse proxy the proxy must forward scheme information (or terminate TLS such that the app observes HTTPS) for `Secure` to be set. The `SameSite=strict` policy provides the primary CSRF defense for this same-origin application; there is no separate CSRF token.

### 3.4 Login rate limiting

Failed logins are recorded in a sliding time window (default: **8 failures per 300 seconds**). While the threshold is exceeded the endpoint returns HTTP 429 and rejects attempts without evaluating credentials. This is a **process-global** counter (appropriate for a single-user application) rather than a per-source-IP limit; operators exposing the instance beyond loopback should also place network-layer rate limiting / fail2ban at the proxy. Every login success, failure, and rate-limit event is written to the audit trail.

### 3.5 Route gating

Every `/api/*` route that touches data or actions requires a valid token via a FastAPI dependency (`require_auth`). The unauthenticated surface is limited to health, first-run setup, auth status, and login/logout.

---

## 4. Secrets Management — The Encrypted Vault

Provider API keys are the most sensitive stored asset. GoFindMe seals them in an application-level vault.

### 4.1 Cryptographic design

| Property | Value |
|----------|-------|
| Key derivation | PBKDF2-HMAC-SHA256, **200,000** iterations, 32-byte (256-bit) derived key |
| Per-secret salt | 16 random bytes (`os.urandom`) |
| Encryption | **AES-256-GCM** (authenticated encryption) |
| Per-secret IV / nonce | 12 random bytes (`os.urandom`) |
| Stored blob format | Base64 JSON `{v, salt, iv, ct}` in `vault_secrets.blob` |

Each secret is encrypted independently with its own salt and nonce, so no two stored blobs share key material even under the same passphrase.

### 4.2 Key lifecycle

- **The passphrase is never stored.** On first unlock, GoFindMe encrypts a fixed known check-value and stores only that check-blob (`vault_meta`). Subsequent unlocks succeed only if the supplied passphrase decrypts the check-blob to the expected value — proving the passphrase without ever persisting it.
- **Unlock holds only the passphrase in memory.** While unlocked, the process retains the passphrase (not a long-lived derived key); the AES key is re-derived per operation from the passphrase and that secret's stored salt, used to decrypt on demand, and then dropped.
- **Idle auto-lock.** After a configurable idle interval (`GOFINDME_VAULT_IDLE_MINUTES`, default 30) the vault locks itself and the passphrase is cleared from memory. Locking is also available on demand.
- **Keys never enter the process environment.** Decrypted keys are passed as function arguments straight into the provider HTTP request (header or query parameter). They are **never** placed in `os.environ`, so they are not exposed to any spawned subprocess, and they are never written to logs or the audit trail (only the provider *name* is audited).

### 4.3 Plaintext-mode caveat (explicit)

A configuration option (`GOFINDME_VAULT_MODE=plaintext`) stores keys **unencrypted** in the database for operators who explicitly accept that trade-off (for example, a fully air-gapped host with disk encryption where an interactive unlock step is undesirable). This mode is **not** the default (the default is `encrypted`), and it materially changes the at-rest guarantee: in plaintext mode a stolen database exposes the API keys directly. Procurement reviewers who require the vault guarantee should mandate `encrypted` mode via configuration policy. The application health endpoint and vault status report the active mode so it can be audited operationally.

---

## 5. Safe Tool Execution

GoFindMe executes real OSINT command-line tools and package managers. This is the highest-risk surface, and it is deliberately funneled through a single, narrow choke point.

### 5.1 No shell, ever

All child processes are spawned with `asyncio.create_subprocess_exec` using an **`argv` list** and **`shell=False`** (implicitly — no shell is ever invoked). No user-influenced string is ever concatenated into a command line and handed to a shell interpreter, which structurally eliminates classic shell-injection.

### 5.2 Strict, anchored target validation

Every investigation target passes a per-type validator before it can reach a subprocess:

- Validators are **fully anchored allowlists** (regular expressions or, for IPs, Python's `ipaddress` parser). A validated value cannot contain whitespace or shell metacharacters.
- Values **cannot begin with `-`** (an explicit argument-injection guard), so a target can never be reinterpreted as a command-line option.
- Types covered: username, real name, email, phone, domain, IP, hash, Bitcoin address, and image (image inputs are file-upload-validated separately, never a free string).
- A maximum length (256 chars) bounds all inputs.

### 5.3 Argv construction

Run templates are split on whitespace **first**, then `{bin}` and `{target}` tokens are substituted **within** individual tokens. Because the split precedes substitution, a target is always exactly one `argv` element and can never introduce additional arguments. Template literal tokens are themselves restricted to a conservative character set. Custom user-defined tools inherit the identical construction path and are validated at save time against a dummy target.

### 5.4 Allowlisting

- **Tools** are an allowlisted registry (a built-in manifest plus operator-defined custom tools). GUI/interactive frameworks are listed for visibility only and are **never** auto-executed.
- Targets are **re-validated server-side at execution time** against the tool's accepted types; the client is never trusted.
- **Tool management** (install/update) accepts only an allowlist of package managers (`pip`, `pipx`, `go`, `git`, `npm`) with refs validated against tight character-class patterns (package names, Go module refs, and `https://` git URLs). Tool management can be disabled entirely with `GOFINDME_ALLOW_TOOL_MGMT=0`, and only the authenticated owner can trigger it.

### 5.5 Provider-side SSRF defenses

- Provider request **hosts are hardcoded** per provider; the user-supplied target only ever populates a URL path or query parameter (URL-encoded by `httpx`), never the host.
- Providers that accept IP targets **refuse private, loopback, link-local, reserved, and multicast addresses** before making a request.
- The HTTP client is configured with **`follow_redirects=False`**, preventing a redirect from steering a request to an unintended host.

### 5.6 Resource bounds

- **Per-job timeouts.** Each tool has a timeout; on expiry the child process is killed and the job is marked `timeout`.
- **Output caps.** Combined stdout/stderr is capped (default 5 MiB per job, configurable) to bound memory and database growth; excess is truncated with a marker.
- **Concurrency caps.** A bounded worker pool plus per-tool sub-caps for heavy tools limit parallel process load.
- **Output sanitization.** Terminal escape sequences and stray control characters are stripped from captured output before storage or display, so tool output cannot corrupt logs or inject terminal/HTML control sequences.

### 5.7 Subprocess environment rationale (documented trade-off)

Child processes inherit the parent environment so that tools function correctly across operating systems (Windows-critical variables such as `SYSTEMROOT`, `TEMP`, `APPDATA`, and `PATHEXT` are required merely to start a process and open a TLS socket). This is safe with respect to secrets because **vault keys are never placed in the environment** (Section 4.2). For **tool-run** jobs the application additionally strips its own outbound proxy and CA-bundle overrides from the child environment, so third-party tools are not silently routed through — or made to trust — the internal proxy/cert; **management** jobs (package installs) retain the proxy and CA so they can fetch packages through the configured path.

---

## 6. Tamper-Evident Audit Trail & Chain of Custody

### 6.1 How the hash chain works

Every security-relevant event — login success/failure, vault unlock/lock, key set/delete, tool and provider execution, case and export actions — is appended to an **append-only SHA-256 hash chain** (`audit_chain` table). Each row stores:

```
hash = SHA-256( prev_hash | timestamp | actor | action | category | detail )
```

The first row binds a fixed genesis value (64 zeros). Each subsequent row binds the previous row's hash, so the rows form a linked chain. Appends are serialized under an in-process lock (the application is single-process, so this is sufficient and correct): each append reads the current tip hash and inserts a new row binding it. The audit path is defensively wrapped so that a logging failure can never break a request, and **secrets are never written to the chain** — only who/what/when metadata.

### 6.2 Verification and pinpointing

`verify()` recomputes the entire chain from genesis and returns `{ok, count, broken_at, tip}`:

- If any historical row was edited, or any row was deleted, the recomputed hash (or the stored `prev_hash` link) will disagree at that point.
- `broken_at` reports the **id of the first divergent row**, pinpointing where tampering begins.
- The verification endpoint (`GET /api/audit/verify`) and the audit listing endpoint both surface integrity status to the operator on demand.

### 6.3 Court / procurement report integrity block

The per-case investigation report (`GET /api/cases/{id}/report`) renders a self-contained, print-optimized HTML document (Print-to-PDF ready) containing case metadata (examiner, legal authority, dates), findings with source provenance, timeline, methodology, and a **Chain of Custody & Integrity** block that includes:

- The live audit-chain verification result (INTACT vs. BROKEN, with the broken entry id if applicable),
- The total audit entry count and the current **audit tip hash**, and
- A **SHA-256 document fingerprint** computed over the rendered report body.

All dynamic values in the report are HTML-escaped.

### 6.4 Honest limitation on the audit chain

The chain is **tamper-evident**, not tamper-proof. It reliably detects and localizes *piecemeal* edits or deletions by any party that cannot (or does not) recompute subsequent hashes. However, because verification recomputes purely from data in the same database and there is **no external trust anchor or signature**, a party with write access to the database *and* knowledge of the (open-source) hashing scheme could rewrite a contiguous suffix of the chain and re-derive consistent hashes, which would then pass `verify()`. Mitigating this fully requires anchoring the tip outside the datastore — for example periodic signing of the tip hash, write-once/WORM storage, or external notarization. These anchoring options are on the roadmap (Section 10). Operators requiring stronger non-repudiation today should periodically export and independently retain (or externally timestamp) the tip hash.

---

## 7. Data at Rest & In Transit

### 7.1 At rest

- **Single SQLite database** in WAL mode holds all application state. The database path is configurable.
- **Vault secrets** in that database are AES-256-GCM encrypted (Section 4). **The remainder of the database — case records, findings, audit rows — is stored unencrypted at the SQLite layer.** Confidentiality of that data at rest therefore depends on **operating-system / full-disk encryption**, which the operator is expected to provide (e.g., LUKS, BitLocker, FileVault). Application-managed database encryption (SQLCipher) is on the roadmap (Section 10).
- **No secrets in logs.** The structured application log and the audit chain record event metadata only; API keys, passwords, and passphrases are never logged.
- **Session tokens** are never persisted (memory only).

### 7.2 In transit

- **Internal (server-side) provider calls** use `httpx` over HTTPS to the providers' hardcoded hosts, with TLS certificate verification enabled by default and an optional operator-supplied CA bundle (`GOFINDME_CA_BUNDLE` / `SSL_CERT_FILE`) for environments with an inspecting proxy or private CA.
- **Operator-to-application transport** is the operator's responsibility to secure. GoFindMe does not terminate TLS itself. Recommended deployment patterns:
  - **Private overlay network** (Tailscale / WireGuard): keep the bind on the tunnel interface, no public ports. A tunnel-provided HTTPS endpoint (for example `tailscale serve`) gives transport encryption with no exposed port and no public certificate management.
  - **TLS reverse proxy** (Caddy / nginx) with a valid certificate for public reachability. The login and cookie-`Secure` behavior assume HTTPS in this case.
  - **Air-gapped / on-prem:** the application runs fully offline for its own operation; only the outbound provider lookups and tool installation require network egress, and both can be omitted or routed through an approved proxy. Loopback-only operation on an isolated host needs no inbound network exposure at all.

---

## 8. Network Exposure & Hardening

### 8.1 Bind posture

- **Loopback by default.** The default bind is `127.0.0.1`, so a fresh install is reachable only from the local host.
- **Wider exposure is explicit and opt-in.** Binding to `0.0.0.0` requires an intentional configuration change (`GOFINDME_BIND`), and the shipped configuration guidance directs operators to do so **only** behind a private tunnel or an authenticated TLS reverse proxy — never raw on the public internet.

### 8.2 Response security headers

A middleware applies the following on every response:

| Header | Value | Purpose |
|--------|-------|---------|
| `Content-Security-Policy` | `default-src 'self'`; `script-src 'self'`; `img-src 'self' data:`; `connect-src 'self'`; `base-uri 'none'`; `form-action 'self'`; `frame-ancestors 'none'` (styles allow `'unsafe-inline'`) | Restricts script/connection origins to self; blocks framing and base-tag hijacking |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME sniffing |
| `Referrer-Policy` | `no-referrer` | Suppresses referrer leakage |
| `X-Frame-Options` | `DENY` | Legacy clickjacking defense (alongside `frame-ancestors 'none'`) |

A deliberately relaxed CSP is applied **only** to two self-contained, inline-script/style documents: the preserved legacy single-file launcher (`/legacy`) and the standalone printable case report (`…/report`). All other routes receive the strict policy above. Reviewers standardizing on strict CSP everywhere can disable serving the legacy launcher.

### 8.3 Other network-facing properties

- **Same-origin only, no CORS.** No cross-origin request handling is enabled.
- **Parameterized SQL only.** All database access uses bound parameters (no string-built SQL), preventing SQL injection.
- **Bounded inputs.** Request bodies use typed models with length limits.

---

## 9. Compliance Posture Mapping

> The following maps **implemented** product capabilities to representative control families in **NIST SP 800-53 Rev. 5**. This is a *support/alignment* aid for the customer's own control-implementation and authorization process. It is **not** a certification, an accreditation, or an attestation of compliance, and it does not assert that any control is fully satisfied by the product alone. Many controls are shared responsibilities that depend on the operator's host, network, and procedural environment.

| Control family | Representative controls | How GoFindMe supports / aligns |
|----------------|------------------------|--------------------------------|
| **AC — Access Control** | AC-3, AC-7, AC-11/AC-12 | Authenticated gating of all data/action endpoints; login rate limiting and lockout window (AC-7); bounded session lifetime and idle vault auto-lock (AC-11/AC-12). *Gap today:* single-user, no role separation (AC-2/AC-6 addressed on roadmap). |
| **AU — Audit & Accountability** | AU-2, AU-3, AU-9, AU-10 | Security events captured with actor/action/category/timestamp (AU-2/AU-3); tamper-evident hash chain with verification and pinpointing protects audit content integrity (AU-9); chain-of-custody report supports accountability/non-repudiation goals (AU-10), subject to the external-anchoring limitation in Section 6.4. |
| **IA — Identification & Authentication** | IA-2, IA-5 | Argon2id credential hashing with minimum-length enforcement and no plaintext storage (IA-5); opaque, non-persistent session tokens (IA-2). *Gap today:* no MFA (IA-2 enhancements on roadmap). |
| **SC — System & Communications Protection** | SC-8, SC-12/SC-13, SC-28, SC-5 | AES-256-GCM with PBKDF2-derived keys for secrets at rest (SC-28/SC-12/SC-13); TLS-verified outbound provider calls and reverse-proxy/tunnel guidance for operator transport (SC-8); resource caps, timeouts, and concurrency limits (SC-5). *Gap today:* whole-database at-rest encryption relies on OS/disk encryption (SQLCipher on roadmap). |
| **SI — System & Information Integrity** | SI-10, SI-7 | Strict anchored input validation, no-shell argv execution, and SSRF guards (SI-10); audit-chain and report fingerprint provide integrity verification of the evidence trail (SI-7). |

### 9.1 CJIS-relevant considerations (informational)

For agencies operating under the FBI **CJIS Security Policy**, the following product properties are relevant to a customer-led assessment. These are considerations, **not** a statement of CJIS compliance:

- **Auditing & accountability (CJIS §5.4):** the tamper-evident audit chain and per-event logging support event-logging and integrity requirements; operators should define retention and review procedures and address the external-anchoring limitation (Section 6.4) for non-repudiation.
- **Identification & authentication (CJIS §5.6):** GoFindMe provides single-factor password authentication today. CJIS advanced-authentication (MFA) expectations for applicable access scenarios are **not** met by the product alone today; MFA and SSO are on the roadmap, and operators can layer an authenticating reverse proxy / IdP in front in the interim.
- **Encryption (CJIS §5.10):** secrets are encrypted with AES-256-GCM; **CJI stored in the database at rest currently depends on FIPS-validated OS/disk encryption supplied by the operator**, and transport encryption depends on the operator's TLS termination. Customers requiring FIPS 140-validated cryptographic modules should validate the underlying platform crypto libraries and disk-encryption modules in their environment.
- **Access control & least privilege (CJIS §5.5):** the current single-user model means personnel separation must be achieved via separate instances and host-level controls until RBAC ships.
- **Physical/host protection:** GoFindMe assumes an operator-controlled, appropriately protected host; physical and media-protection controls are the operator's responsibility.

---

## 10. Known Limitations & Security Roadmap

GoFindMe states its current boundaries plainly so that procurement reviewers can plan around them.

### 10.1 Known limitations (present state)

- **Single-user only.** One owner account; no roles, groups, per-record ownership, or tenant isolation within a process. Team separation requires separate instances.
- **No MFA.** Authentication is single-factor (password) today.
- **Database not encrypted as a whole at rest.** Only vault secrets are encrypted by the application; confidentiality of case/audit data at rest depends on OS/disk encryption provided by the operator.
- **Audit chain has no external trust anchor.** Tamper-*evident* against piecemeal edits, but a party with database write access and the hashing scheme could rewrite a consistent suffix (Section 6.4).
- **Application does not terminate TLS.** Transport security for operator access depends on a reverse proxy or private tunnel.
- **Vault passphrase resides in memory while unlocked**, and secrets are not held in an OS keystore/HSM; a root-level host compromise can read them.
- **Login rate limiting is process-global**, not per-source-IP; network-layer throttling is recommended for any non-loopback exposure.
- **No signed release/update verification** is enforced by the application; the self-updating launchers pull source without in-product signature verification.

### 10.2 Security roadmap (planned, not yet implemented)

- **Multi-user & RBAC / SSO:** user directory, role-based authorization, per-case ownership, and identity federation (OIDC/SAML).
- **Multi-factor authentication:** TOTP/WebAuthn for the owner and future users.
- **Full database-at-rest encryption:** application-managed encrypted storage (e.g., SQLCipher), independent of OS disk encryption.
- **Secrets in an HSM / OS keystore:** move the vault key material into an OS keychain or hardware security module rather than process memory.
- **Signed releases & verified updates:** cryptographically signed artifacts with signature verification in the launchers/packaged builds.
- **Externally anchored audit chain:** periodic tip signing / notarization / WORM export to close the wholesale-rewrite gap and strengthen non-repudiation.

---

## Appendix A — Configuration Reference (security-relevant)

| Variable | Default | Security relevance |
|----------|---------|--------------------|
| `GOFINDME_BIND` | `127.0.0.1` | Network exposure; keep loopback unless behind a tunnel/TLS proxy |
| `GOFINDME_PORT` | `8000` | Listen port |
| `GOFINDME_VAULT_MODE` | `encrypted` | `plaintext` disables at-rest key encryption (accepted-risk mode) |
| `GOFINDME_VAULT_IDLE_MINUTES` | `30` | Idle auto-lock interval for the vault |
| `GOFINDME_TOKEN_TTL_DAYS` | `7` | Session token lifetime |
| `GOFINDME_MAX_CONCURRENCY` | `4` | Bound on concurrent tool/provider jobs |
| `GOFINDME_ALLOW_TOOL_MGMT` | `1` | Set `0` to disable in-dashboard package installs/updates |
| `GOFINDME_CA_BUNDLE` / `SSL_CERT_FILE` | unset | CA bundle for outbound provider TLS (private CA / inspecting proxy) |
| `GOFINDME_OUTPUT_CAP` | `5 MiB` | Per-job captured-output cap |

## Appendix B — Recommended Hardening Checklist for Operators

1. Run GoFindMe under a dedicated **non-root** service account.
2. Enable **full-disk / filesystem encryption** on the host (covers case and audit data at rest until SQLCipher ships).
3. Keep `GOFINDME_VAULT_MODE=encrypted`; use a strong, unique vault passphrase.
4. Do **not** expose the port to the public internet; use **Tailscale/WireGuard** or an **authenticated TLS reverse proxy**.
5. Terminate TLS at the proxy and forward scheme so the session cookie's `Secure` flag applies.
6. Add network-layer rate limiting / fail2ban at the proxy for any non-loopback deployment.
7. Set `GOFINDME_ALLOW_TOOL_MGMT=0` in locked-down environments where tool installation should be out-of-band.
8. Periodically call `/api/audit/verify` and **export/retain the audit tip hash externally** to strengthen chain-of-custody assurance.
9. Restrict OS file permissions on the database and back it up to protected storage.
10. Provision a separate instance per investigator/team until multi-user RBAC is available.

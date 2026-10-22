# Authentication setup and current limitations

The application supports password sign-in, optional authenticator-app
two-factor login, WebAuthn passkeys, recovery codes, invite-based household
registration, and revocable server-side sessions. These controls are not a
substitute for an independent security audit.

## Local development

From the repository root:

```powershell
venv\Scripts\python.exe -m flask run
```

Open `http://127.0.0.1:5000/login`. Development uses an in-memory rate-limit
backend and does not require SMTP or Redis.

For a new household, use the household-invite registration flow below. Legacy
account-creation scripts have been removed; do not restore hard-coded accounts
or credentials from old setup instructions.

When `SECRET_KEY` is not configured, development automatically generates a random
key in `instance/development_secret_key` and reuses it across restarts and code
reloads. The instance directory is ignored by Git; keep this key private and do
not use it for production. An explicitly configured `SECRET_KEY` takes precedence.
Deleting the file generates a new key on the next startup and invalidates existing
login cookies. Unreadable or invalid key files cause startup to fail rather than
silently signing everyone out.

Select **Remember Me** to stay signed in for up to seven days, including across
server restarts. Without Remember Me, sessions expire after the configured idle
and absolute limits (60 minutes and 12 hours by default). Session revocation and
the other authentication controls are described below.

## Production prerequisites

Install `requirements.txt`, select `FLASK_ENV=production`, and configure:

| Setting | Requirement |
| --- | --- |
| `SECRET_KEY` | Stable random secret, at least 32 characters |
| `DATABASE_URL` or `SQLALCHEMY_DATABASE_URI` | Application database connection |
| `RATELIMIT_STORAGE_URI` | Shared private Redis backend, using `redis://` or `rediss://` |
| `TRUSTED_PROXY_COUNT` | `0` by default; `1` for the supplied single nginx proxy |
| `TRUSTED_PROXY_IPS` | Recommended: the proxy's IP (comma-separated IPs/CIDRs). Only it and localhost may connect; others get 403 |

For example, generate a secret locally:

```powershell
venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Store it in the deployment environment, not source control. Startup fails when
required production settings are missing, the secret is too short, or rate-limit
storage is not Redis. Redis connection failures are not silently ignored.

On an existing server, run `deployment/setup_redis.sh` once to install Redis and add
these settings; `deployment/check_production_config.py` verifies them (and is run
automatically by `quick_update.sh` before restarting). See `deployment/README.md`.

Only trust forwarded headers when the application server is reachable exclusively
through the configured trusted proxies. Setting `TRUSTED_PROXY_IPS` enforces this in
the app: forwarded headers are used only on connections from those addresses,
loopback (local health checks) is served without trusting them, and every other
direct connection gets 403. Review the actual proxy chain before
changing the count; nginx plus another proxy is not the single-proxy example.
See [Deployment setup](../deployment/README.md).

## Current controls

- Login POSTs: 10 per minute per client IP and 20 per hour per normalized email.
  Email-based rate-limit keys are hashed; these limits also apply to unknown users.
- Registration and invitation-join POSTs: 5 per hour per client IP, per endpoint.
  Invitation tokens share an endpoint limit rather than creating separate buckets.
- Existing general request limits remain in place. Authentication GETs do not
  consume POST-attempt buckets. Exceeding a limit returns HTTP 429.
- Five failed password attempts lock an account for 15 minutes. Login failures
  use the same public message for incorrect, unknown, locked, and inactive accounts.
  Expired lockouts start a new failure window. Unknown users still incur a password
  hash check; this is not a guarantee of identical response timing.
- Registration and invited-member signup use the same
  configured password policy: at least 10 characters with uppercase, lowercase,
  number, and supported special character. Existing passwords are not invalidated.
- Login business rules live in `AuthService`. Invalid registration passwords are
  rejected before creating a household.
- Post-login redirects accept only local absolute paths, not external URLs,
  schemes, backslashes, or control characters.
- Logout requires a CSRF-protected POST. It revokes the current server-side session and
  clears the session and remember-me cookie. Other devices stay signed in unless you sign them out (see below).
- Deactivated users cannot be restored from an existing session or remember cookie.
- Production session and remember-me cookies use Secure, HttpOnly, and SameSite=Lax.
  Remember-me cookies last seven days and are not renewed on every request.
- Non-static application responses use `Cache-Control: no-store`.

## Household invites (invite-only registration)

New households can only register with a one-time invite link unless
`ALLOW_OPEN_REGISTRATION=true` is set in the environment (default: off).
Invites are single-use, expire after 1-30 days (default 7), can be restricted
to one email address, and can be revoked. Only a SHA-256 hash of each token is
stored, so the link is shown once when created. A failed registration (weak
password, existing email) does not consume the invite.

Issue invites from the account menu → **Site admin area → Household invites**
(`/site-admin/household-invites`), or on the server:

```bash
flask site-admin grant you@example.com          # once, to see the menu item
flask household-invite create --note "Smiths" --email smiths@example.com --base-url https://your-domain
flask household-invite list
flask household-invite revoke <id>
```

Family member invites (`/family/join/<token>`) are unchanged.

Flask sessions are still signed client-side cookies, not encrypted storage.
Never store financial records or authentication secrets in them. Login itself is
controlled by a server-side session record (see **Signed-in sessions**), so a
stolen cookie stops working once that session is revoked or expires.

## Passkeys (passwordless sign-in)

Passkeys use WebAuthn with required device/user verification (face, fingerprint,
device PIN or a verification-capable security key). A verified passkey replaces
both the password and authenticator-code steps for that sign-in. Password + TOTP
and existing recovery codes remain available as a fallback; adding a passkey
does not turn TOTP off.

Deployment:

1. Install the updated `requirements.txt` (`webauthn==2.7.0`).
2. Back up the database and run `flask db upgrade` (revision `b9e4a7c1d6f2`).
   Existing sessions are preserved; their authentication method defaults to
   `password`.
3. Set `PASSKEY_ORIGIN=https://finance.yourdomain.co.uk` to the exact public origin
   without a path. It defaults to `APP_BASE_URL` when omitted.
   `PASSKEY_RP_ID` defaults to that origin's hostname (no scheme or port).
   Trust settings are never inferred from the request Host header.
4. Restart the application. Open **Account security → Passkeys**, give the key a
   name, and select **Add a passkey**. Add a second device/key for recovery.
5. Use **Sign in with a passkey** on the sign-in page. Email and password fields
   are not needed; **Remember Me** still controls the seven-day session.

Passkeys are disabled if neither origin setting is configured. Production
requires HTTPS and a stable domain; changing the RP ID invalidates existing
passkeys for the new site. Local development can use
`PASSKEY_ORIGIN=http://localhost:5000` (or `http://127.0.0.1:5000`, used consistently).
Unsupported browsers show an explicit message and keep password sign-in available.

- Up to 20 named passkeys per user; registration requires a discoverable
  credential and user verification. No attestation or biometric data is retained.
- Only credential IDs, public keys, counters, names and timestamps are stored
  in `user_passkeys`. Private keys stay in the authenticator/password manager.
- Five-minute challenges are browser-, purpose- and account-bound, stored in
  `passkey_challenges` and atomically consumed once. Restoring an old signed cookie
  cannot replay a consumed challenge. Expired challenges are pruned on new requests.
- Every response verifies the challenge, RP ID, trusted origin and user
  verification. Sign-in verifies the signature and signature counter (including
  zero-counter support for synced passkeys). Inactive/locked accounts and removed
  credentials cannot sign in.
- All passkey POSTs require CSRF protection and are rate-limited. Registration
  and removal require recent authentication. Changes sign out other sessions
  and produce security events and configured email alerts.
- **Confirm with a passkey** can refresh the recent-authentication window without
  entering a password. Actions which explicitly require the current password
  (such as changing it or deleting the account) still require it.
- Site admins can use a verified passkey session instead of TOTP enrollment.
  A password-only session with existing passkeys and no TOTP cannot access admin
  pages, replace/remove passkeys, or enroll TOTP without confirming an existing
  passkey first. They cannot remove their last passkey unless TOTP is enabled.
- Losing a passkey does not invalidate its private key. Remove it from **Account
  security**; remove it from your password manager/device separately if desired.

If all passkeys are lost, use password + authenticator/recovery code if enabled.
For a passkey-only site admin, the server operator must verify identity offline,
then run:

```bash
flask passkeys reset user@example.com
```

This removes all passkeys and pending challenges, revokes every session, records
an audit event and sends a configured security alert. It does not reset TOTP.
A site admin without TOTP can then sign in with their password and enroll a new
passkey from Account security or set up TOTP.

## Two-factor login

Any user can turn on authenticator-app (TOTP) two-factor login from
**Account security** in the user menu. Site admins must have either TOTP enabled
or a passkey-verified session. A site admin without either is redirected to setup
(or passkey confirmation if they already have passkeys).

- Setup shows a QR code and a manual setup key. The first valid 6-digit code
  turns it on and shows 10 single-use recovery codes once.
- Login becomes password, then a 6-digit code (or a recovery code). The
  password-verified step expires after 5 minutes. The code step is rate-limited
  per IP and per account (5 attempts per 15 minutes).
- Codes are accepted for one 30-second step either side of the current one.
  Each code can only be used once, which protects against replay.
- Recovery codes are stored as SHA-256 hashes. Regenerating them needs the
  password, and turning 2FA off needs the password and a code. Site admins
  can only turn it off if they have at least one registered passkey.
- The TOTP secret is stored unencrypted in the `users` table, so protect the
  database and backups. It is hidden from the admin panel lists, forms and exports.

Lost device and recovery codes: on the server, run

```bash
sudo -u joneshq bash -c "cd /home/joneshq/joneshq-finance && venv/bin/flask two-factor reset user@example.com"
```

The user can then sign in with their password and set it up again.

Turning 2FA on signs out every other session for that user, including
"remember me" logins that never passed a code. The reset command above also
signs the user out everywhere.

## Signed-in sessions

Every login creates a row in `user_sessions`. The browser holds a random token
inside its session and remember-me cookies; the database stores only its SHA-256
hash. Each request checks that row, so a session can be ended from the server
at any time.

- A normal login ends after `SESSION_IDLE_MINUTES` of inactivity (default 60) or
  `SESSION_ABSOLUTE_HOURS` after sign-in (default 12), whichever comes first.
- A "remember me" login lasts 7 days (`REMEMBER_COOKIE_DURATION`) with no idle timeout.
- Activity (`last_seen_at` and IP) is recorded at most once a minute.
- **Account security → Signed-in devices** lists active sessions with browser,
  device, IP and last activity. Users can sign out one device or all other devices.
- Site admins can view all sessions (without token hashes) under **Site admin area → Users & audit console → Operator → Sessions**.
- Revoked and expired rows are deleted 30 days later, the next time that user signs in.

Sign a user out everywhere from the server (e.g. a lost laptop):

```bash
sudo -u joneshq bash -c "cd /home/joneshq/joneshq-finance && venv/bin/flask sessions revoke user@example.com"
```

Sessions from before this feature are not recognised, so everyone is signed out
once when it is deployed.

## Change password, password confirmation and security log

- **Account security → Change password** needs the current password and a new one
  that meets the password policy. It signs out every other device.
- Sensitive actions ask for password or passkey confirmation if neither was used in the last
  `REAUTH_WINDOW_MINUTES` (default 15) in this session: turning on two-factor
  login, household invites, service settings, family invites, editing or removing family members,
  and the site admin area. The time is counted from the last password/passkey verification and
  doesn't slide with activity. "Remember me" sessions keep their original sign-in
  time, so they are asked once that is older than the window. Form posts can't be replayed, so the user goes
  back to the page they came from and submits again. Password confirmation is
  rate-limited (5 per 15 minutes per user) but doesn't count towards lockout.
- Removing a family member signs them out of every device straight away.
- Security events are stored in `security_events`: sign-ins, failed sign-ins
  and lockouts, sign-outs and revoked sessions, password confirmations and
  changes, two-factor changes, invites and family member changes, and the
  server reset commands. Each row has the user, household, IP and browser.
  Failed sign-ins for unknown emails are not recorded.
- **Account security → Recent security activity** shows a user their last 20 events.
  Site admins can search all events under **Site admin area → Users & audit console → Operator → Security events**.

- Events older than `SECURITY_EVENT_RETENTION_DAYS` (365) are deleted when anyone signs in.
  Enable the optional daily systemd retention timer to clean up even without sign-ins
  (see [deployment setup](../deployment/README.md#daily-retention-cleanup)).

## Roles: household owner vs site admin

There are two unrelated kinds of "admin". Neither grants the other's powers.

| | Household owner | Site admin (service operator) |
|---|---|---|
| Stored as | `users.role = 'admin'` (`User.is_household_owner`) | `users.is_site_admin` |
| Who | Whoever registers a household, plus anyone they make an owner | You, the operator. Granted only on the server: `flask site-admin grant EMAIL` |
| Scope | Their own household only (`family_id`) | The service as a whole, never household finances |
| Where | **Family & members**, Settings, household deletion | **Site admin area** (`/site-admin`) |
| Requirements | None beyond sign-in | TOTP enrollment or a passkey-verified session, plus recent authentication |

The operator normally also owns their own household and uses the app like any
other customer. The user menu separates **Your household**, **Your account** and
**Site admin (all households)**; every site-admin page carries a red striped
banner with **Back to my household**.

## Site admin area (`/site-admin`)

Only site admins with TOTP enabled or a passkey-verified session, and recent
password/passkey authentication, can open it. Nothing here shows household financial data.

- **Overview** (`/site-admin/`): counts (households, active/deactivated/locked
  users, sessions, open household invites, failed sign-ins in 24 hours) and the
  effective server configuration from `.env.production` (registration mode, email,
  session limits, retention, rate-limit storage scheme, database engine and
  migration). Read-only; secrets are never shown.
- **Household invites** (`/site-admin/household-invites`): one-time registration
  links for new households.
- **Service settings** (`/site-admin/settings`): switches stored in the
  `site_settings` table that take effect immediately:
  - **Pause new household sign-ups**: blocks household registration even with a
    valid invite and shows an optional message instead. Existing households,
    sign-ins and family member invites are unaffected.
  - **Announcement**: plain-text banner (information, warning or urgent) at the
    top of every app page, including sign-in. Leave blank to remove it.

  Changes are recorded as a `site_settings_updated` security event.
- **Users & audit console** (`/site-admin/console`, Flask-Admin; the old `/admin`
  address redirects to the site admin area):
  - **Users** is read-only, with secrets excluded (password hash, two-factor
    secret, recovery codes). Bulk actions: **Deactivate** (blocks sign-in and
    signs out every device; you can't deactivate yourself), **Reactivate**,
    **Unlock** (clears failed-sign-in lockout) and **Sign out everywhere**. Each
    is recorded as a security event (`account_deactivated`,
    `account_reactivated`, `account_unlocked`, `all_sessions_revoked`) with
    "by site admin <id>".
  - **Households, Member invites, Household invites, Sessions** and **Security
    events** are read-only. Invite tokens and token hashes are never shown, so
    the console can't be used to join a household.
  - **Reference → Tax year templates** edits only the global tax rows
    (`family_id` empty) that new households copy and that act as the fallback.
    Each household's own tax settings are edited by that household in Settings.
  - All console forms and bulk actions carry Flask-Admin CSRF tokens. Users
    can't be created, edited or deleted there; use **Account security**, family
    member management, household deletion or the `flask` server commands so
    validation and audit logging still apply.

## Email: password reset, confirmation and security alerts

Email is off until `MAIL_SERVER` and `MAIL_FROM` are set (see `.env.example`).
Any SMTP provider works; Resend's free tier is the documented example. In
production `APP_BASE_URL` must be an `https://` address: every emailed link is
built from it, never from the request's Host header.

Quote sender values containing spaces or angle brackets, for example
`MAIL_FROM='Family HQ <noreply@yourdomain.co.uk>'`. This also keeps the assignment
valid when loading the environment file in Bash.

- **Forgot password?** on the sign-in page emails a reset link. The response is
  the same whether or not the address has an account. Limited to 5 requests per
  hour per IP and 3 per hour per email address.
- Reset links are signed with `SECRET_KEY`, expire after `PASSWORD_RESET_MINUTES`
  (60), and stop working once the password changes, so each works once. Opening
  the link moves the token into the session and redirects to `/reset-password`,
  so it isn't left in browser history or sent as a Referer.
- Resetting a password clears any lockout and signs out every device. Two-factor
  login is still required at the next sign-in.
- New accounts (household registration and family invites) get a confirmation
  email. Unconfirmed users can resend it from **Account security**. A reset
  link received by email also confirms the address.
- Security alert emails are sent for: sign-in from a browser not seen before
  (not the first sign-in), password changed or reset, two-factor login turned
  on, off or reset, new recovery codes, and passkeys added, removed or reset.
- Email is sent in a background thread so pages don't wait on SMTP; failures are
  logged. Check delivery with `flask email test you@example.com`.
- Without email, or for someone who can't reach their inbox, the server admin can
  run `flask users reset-link user@example.com` and pass the link on privately.
  It lasts `ADMIN_PASSWORD_RESET_HOURS` (24) and also works once.

## Public privacy notice

`/privacy` is public, linked in the shared footer, storage notice, household
registration and family-join form. It remains accessible before mandatory
site-admin two-factor setup. It describes operator access (not just household
visibility), exports, individual/household deletion, retained history and security
events, email processing, rights/contact and retention limitations.

The published operator details are Keiron Jones, `keirontj@gmail.com`, UK
application hosting, public-service audience with invitation-controlled signup,
and Resend for outgoing email. The operator selected service delivery as the basis
for necessary account-holder features and legitimate interests for security,
abuse prevention and operational backups. These are operator policy statements,
not a legal-compliance certification. Review the basis for records about
non-account-holders, especially children, before broader public use.

No fixed backup/operational-log retention has been confirmed. The notice says so
explicitly; provider/support-email retention and international processing
locations/safeguards are not specified. The operator must verify provider
arrangements and set appropriate retention rather than treating publication
as resolving those issues. Do not promise UK-only processing simply because the
application server is in the UK. Update the template/date when operator details,
providers, retention, purposes or behaviour change. Security-event retention is
rendered from configuration. No consent checkbox, tracking or migration is added.

## User-visible data export and lifecycle limitations

**Account security → Download JSON export** returns the signed-in user's profile
and explicitly allowlisted financial fields from supported sections. It uses
family-scoped queries and record visibility; household and site admins do not
gain access to other members' private records through this download. Shared
accounts still include their visible transactions, regardless of privacy on a
linked income or other source record.

The POST requires CSRF protection and a recent password confirmation, is limited
to two downloads per hour per user, and records a `data_exported` security event.
The response is an attachment with `Cache-Control: no-store`. Downloads contain
sensitive personal and financial information: keep them secure after saving.

The version-1 JSON format includes `exported_at`, `profile`, `sections`, `data`,
`excluded` and `notes`. Data tables are keyed by their database table names, with
IDs for cross-references. Decimal amounts are strings and dates use ISO 8601.
Linked rows may be absent when the user lacks access. It is not a restorable
database backup or a guaranteed point-in-time snapshot; avoid concurrent edits
while downloading.

Supported source data covers accounts and balances, transactions/subscriptions/
planned transactions, categories/budgets, vendors/types, credit cards and
promotions/transactions, loans/payments/term changes, income and recurring income,
pensions/snapshots, properties/mortgages and their snapshots/payments,
vehicles/fuel/trips, expenses, childcare and plans/items. Sections not granted to
the user are omitted altogether.

Explicit exclusions include other users' profiles, credentials, two-factor
secrets, recovery codes, sessions, invites, security events, server configuration,
settings, logs and backups. Cached totals, net-worth snapshots, monthly summaries
and reimbursement/calendar metadata are also excluded. The service's explicit
field list must be reviewed when adding models or fields; new database columns
are not exported automatically. No downloaded files are retained by the app.

Member removal is not account erasure: it clears household membership and revokes
sessions, leaving the account and financial records in place. Private records
keep their owner.

### Individual account deletion

Account security links to a deletion review at `/account/security/delete`.
Deletion requires recent password confirmation, the current password again,
CSRF protection and the exact phrase `DELETE MY ACCOUNT`. POST attempts are
limited to three per 15 minutes per user. Review counts are recalculated on
submission. Only the signed-in user can delete their account.

The operation deletes the user, all their sessions/recovery codes and their
privately owned accounts, cards, income/recurring income, expenses, loans,
pensions, vehicles and plans. Domain children are deleted with their parent,
including private account/card transactions, subscriptions, balances, payments,
snapshots, fuel records, trips and plan items. Records still owned in former
households are included, even after household membership has been removed.

Shared records and other members' private records remain. Nullable links to
deleted records are detached, including shared bank entries linked to a private
income, expense, loan or card. Amounts, balances, names and free text in retained
history are not anonymised; shared records are not recalculated or regenerated.
Authored family-join invites are deleted and pending authored household-registration
invites are revoked. Prior security events remain under normal retention with
their user link removed; IP addresses or other identifying details may remain.

The last household owner must make another active member an owner first.
Site administrators must first have their role revoked on the server with
`flask site-admin revoke EMAIL`. A household-row write serializes this deletion
path's administrator checks; it is not a global lock for unrelated membership edits.
Inconsistent household links or unhandled required/private-owner dependencies
block deletion rather than exposing records or removing another household's data.
Deletion uses one transaction and rolls back on database failure. Success signs
out this browser, clears its remember cookie and invalidates all other sessions.

This is not household deletion or complete erasure of every copy. Backups,
operational logs, email-provider records, previously downloaded copies and
browser display preferences are outside this operation. Operator privacy/deletion
policies remain separate work.
No database migration is required. When adding owned models, domain children or
foreign keys, review the deletion plan/order and test with foreign keys enabled.

### Whole-household deletion

Family Management has a separate deletion review at `/family/delete`, below the
ordinary management controls. One active administrator of that household can
confirm deletion, including other members' private records; other administrators
do not need to approve. The page lists affected members and table counts without
showing their private financial contents.

The review requires recent authentication, the current password, CSRF protection,
the exact phrase `DELETE THIS HOUSEHOLD` and a hidden reviewed household ID.
Attempts are limited to three per 15 minutes per user. Authorization, membership
and counts are rechecked under a household-row write on submission. A different
household cannot be selected through form/query parameters.

All records scoped to that household are deleted, including private records owned
by current or former members, financial children, childcare, properties/mortgages,
categories, vendors, settings, cached summaries and family-join invites. Global
templates and other households remain unchanged. New household tables require an
explicit deletion-rule review; inconsistent incoming cross-household links or
unhandled required dependencies block deletion. Data deletion, membership clearing,
session revocation and audit recording commit in one transaction or roll back together.
Avoid concurrent data/membership changes during deletion; this path is not a
global lock for unrelated application writers.

Every current member (including inactive members) retains their login account,
active/inactive status, password, email, site-admin flag, two-factor configuration
and recovery codes. Household membership, role, section grants, display name and
default account are cleared; all their sessions are revoked. Former members'
accounts/sessions are not changed. Existing security events retain their user link
but lose the deleted household link; each current member receives a retained
`household_deleted` event. Operational logs record a completion marker without
financial details. Backups, logs, provider records and downloaded copies remain
outside this operation and follow separate retention policies.

The administrator's export does **not** include other members' private data.
Members should download their own exports before deletion if wanted; the review
warns about this. There is no automatic full-household export or emailed backup.
After signing back in, detached users land on Account security. They can accept
a fresh family-join invite while signed in, following recent password confirmation,
using the same account. This consumes the invite once, assigns its permissions
and revokes prior sessions before starting a new one. Ordinary registration still
creates new accounts; it does not recreate households for an existing email.
No migration or additional scheduled job is required.

### Retention cleanup

Security-event cleanup runs on sign-in (365 days by default);
old session cleanup runs when that user creates a session. The server command
`flask maintenance cleanup` also cleans both across all households, with
`--dry-run` for preview. It retains sessions until more than 30 days after absolute
expiry or revocation, not merely idle expiry. The optional daily systemd timer
must be installed and enabled separately; it is not activated by deployment.
Backup retention and operator privacy/deletion policies remain separate.

## Validation

Werkzeug is pinned to 3.1.9, replacing 3.0.1, which was affected by the
development-debugger advisory
[CVE-2024-34069](https://github.com/pallets/werkzeug/security/advisories/GHSA-2g68-c3qc-8985).
Install the updated requirements in each environment; changing the pin alone
does not update a running server. Never expose the development debugger in
production. This targeted upgrade is not a complete dependency security audit.

```powershell
venv\Scripts\python.exe -m pytest -q tests\test_auth_security.py tests\test_auth_service.py tests\test_user.py tests\test_onboarding.py tests\test_household_invites.py tests\test_two_factor.py tests\test_passkeys.py tests\test_user_sessions.py tests\test_account_security.py tests\test_account_email.py
```

Tests cover rejected and successful logins, lockout expiry, safe redirects,
IP/account throttling, invitation policy, two-factor setup/login/recovery/replay,
real signed passkey registration/authentication, trusted origin/RP/device verification,
challenge and counter replay, account-bound confirmation, site-admin factor enforcement,
session revocation and idle/absolute expiry, change password, password confirmation
for sensitive actions, security events, password reset by email and admin link,
email confirmation, security alert emails,
logout/CSRF, cookie attributes, deactivation, cache headers, and production validation.

Before deploying, verify HTTPS cookie attributes and rate limits through the real
reverse proxy, including requests distributed across workers. Automated local
tests use memory storage; they do not prove production Redis availability or
correct proxy configuration.

## Remaining work before wider public registration

- Choose managed identity, self-hosted identity, or continued local authentication.
- Review household isolation, exports, administrative access, and member removal.
- The public `/cookies` notice describes application cookies, local-storage
  preferences and account email delivery. Main-app Bootstrap, icons and Chart.js
  assets are bundled locally with upstream licenses under `static/vendor/`;
  system fonts replace Google Fonts. Flask-Admin uses its package's local assets.
  Maintain this inventory when adding features. A full operator privacy policy
  and any consent requirements still need review before wider registration.
- Verify backups, restore procedures, monitoring, and dependency maintenance.

Household registration is invite-only by default. Registration and invitation
validation can still reveal to an invite holder that an email is already
registered. Email confirmation is not yet required to use the app.

# Authentication setup and current limitations

The application uses Flask-Login, Werkzeug password hashing, and Flask-WTF CSRF
protection. This is a hardened password-login foundation, not a complete public
financial-service identity system.

## Local development

From the repository root:

```powershell
venv\Scripts\python.exe -m scripts.create_initial_users
venv\Scripts\python.exe -m flask run
```

Open `http://127.0.0.1:5000/login`. Development uses an in-memory rate-limit
backend and does not require SMTP or Redis.

## Production prerequisites

Install `requirements.txt`, select `FLASK_ENV=production`, and configure:

| Setting | Requirement |
| --- | --- |
| `SECRET_KEY` | Stable random secret, at least 32 characters |
| `DATABASE_URL` or `SQLALCHEMY_DATABASE_URI` | Application database connection |
| `RATELIMIT_STORAGE_URI` | Shared private Redis backend, using `redis://` or `rediss://` |
| `TRUSTED_PROXY_COUNT` | `0` by default; `1` for the supplied single nginx proxy |

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
through the configured trusted proxies. Review the actual proxy chain before
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
- Registration, invited-member signup, and account-creation scripts use the same
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

Issue invites as a site admin from the account menu → **Household invites**
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

## Two-factor login

Any user can turn on authenticator-app (TOTP) two-factor login from
**Account security** in the user menu. It is **required for site admins**: a
site admin without it is redirected to setup on every page, and `/admin` refuses
access until it is on.

- Setup shows a QR code and a manual setup key. The first valid 6-digit code
  turns it on and shows 10 single-use recovery codes once.
- Login becomes password, then a 6-digit code (or a recovery code). The
  password-verified step expires after 5 minutes. The code step is rate-limited
  per IP and per account (5 attempts per 15 minutes).
- Codes are accepted for one 30-second step either side of the current one.
  Each code can only be used once, which protects against replay.
- Recovery codes are stored as SHA-256 hashes. Regenerating them needs the
  password, and turning 2FA off needs the password and a code. Site admins
  can't turn it off.
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
- Site admins can view all sessions (without token hashes) under **Admin → Core → Sessions**.
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
- Sensitive actions ask for the password again if it wasn't entered in the last
  `REAUTH_WINDOW_MINUTES` (default 15) in this session: turning on two-factor
  login, household invites, family invites, editing or removing family members,
  and the `/admin` panel. The time is counted from the last password entry and
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
  Site admins can search all events under **Admin → Core → Security events**.
- Events older than `SECURITY_EVENT_RETENTION_DAYS` (365) are deleted when anyone signs in.

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
  on, off or reset, and new recovery codes.
- Email is sent in a background thread so pages don't wait on SMTP; failures are
  logged. Check delivery with `flask email test you@example.com`.
- Without email, or for someone who can't reach their inbox, the server admin can
  run `flask users reset-link user@example.com` and pass the link on privately.
  It lasts `ADMIN_PASSWORD_RESET_HOURS` (24) and also works once.

## Validation

```powershell
venv\Scripts\python.exe -m pytest -q tests\test_auth_security.py tests\test_auth_service.py tests\test_user.py tests\test_onboarding.py tests\test_household_invites.py tests\test_two_factor.py tests\test_user_sessions.py tests\test_account_security.py tests\test_account_email.py
```

Tests cover rejected and successful logins, lockout expiry, safe redirects,
IP/account throttling, invitation policy, two-factor setup/login/recovery/replay,
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
- Add passkeys as an alternative to authenticator-app codes.
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

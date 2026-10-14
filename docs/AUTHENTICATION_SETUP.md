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
- Logout requires a CSRF-protected POST. It clears the current session and
  remember-me cookie; it does not revoke other devices.
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
Never store financial records or authentication secrets in them. The configured
session lifetime is not a server-enforced idle timeout or a revocation mechanism.
Deleting or expiring the current browser's cookie does not invalidate a stolen
copy of it.

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

Known limitation: "remember me" cookies issued before a user turned on 2FA stay
valid until they expire. Revocable sessions are planned to fix this.

## Validation

```powershell
venv\Scripts\python.exe -m pytest -q tests\test_auth_security.py tests\test_auth_service.py tests\test_user.py tests\test_onboarding.py tests\test_household_invites.py tests\test_two_factor.py
```

Tests cover rejected and successful logins, lockout expiry, safe redirects,
IP/account throttling, invitation policy, two-factor setup/login/recovery/replay,
logout/CSRF, cookie attributes, deactivation, cache headers, and production validation.

Before deploying, verify HTTPS cookie attributes and rate limits through the real
reverse proxy, including requests distributed across workers. Automated local
tests use memory storage; they do not prove production Redis availability or
correct proxy configuration.

## Remaining work before wider public registration

- Choose managed identity, self-hosted identity, or continued local authentication.
- Add verified email ownership and safe recovery with dependable email delivery.
- Add passkeys as an alternative to authenticator-app codes.
- Add revocable sessions, idle/absolute expiry, logout everywhere, and sensitive-action
  reauthentication.
- Review household isolation, exports, administrative access, and member removal.
- Add security notifications and audit events.
- Inventory browser storage and external assets; provide accurate privacy/storage
  notices and consent controls where required.
- Verify backups, restore procedures, monitoring, and dependency maintenance.

Household registration is invite-only by default. Registration and invitation
validation can still reveal to an invite holder that an email is already
registered. SMTP, email verification, and password recovery are not yet implemented.

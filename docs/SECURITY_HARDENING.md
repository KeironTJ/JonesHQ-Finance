# Security Controls and Deployment Requirements

This guide summarizes controls implemented in the application. It is not a
security audit or a guarantee of production readiness. The current production
configuration and operational steps are maintained in the
[production runbook](../deployment/README.md); application code and configuration
remain authoritative.

## Application Controls

- **CSRF protection:** Flask-WTF protection is enabled in normal configurations.
  Tests explicitly disable it.
- **Password hashing and policy:** Werkzeug password hashing is used. New
  passwords must meet the configured minimum of 10 characters and include
  uppercase, lowercase, numeric, and supported special characters. Existing
  passwords are not retroactively invalidated.
- **Login throttling:** Password login POSTs are limited to 10 per minute per
  client IP and 20 per hour per normalized account key. Other authentication
  endpoints have their own limits; there is no single rate applicable to every
  route.
- **Account lockout:** Five failed password attempts lock an account for 15
  minutes. This complements rate limiting; it does not replace it.
- **Multi-factor sign-in:** Users can enable authenticator-app TOTP and use
  single-use recovery codes. Passkeys use WebAuthn with origin and relying-party
  verification. Passkey and TOTP setup, recovery, and removal have additional
  authentication and throttling requirements.
- **Session lifecycle:** Server-side session records support revocation.
  Non-remembered sessions expire after 60 minutes idle or 12 hours absolute by
  default. Remember-me sessions last up to seven days. Sensitive actions can
  require recent authentication.
- **Cookies and responses:** Production session cookies use Secure, HttpOnly,
  and SameSite=Lax. Non-static application responses are marked `no-store`.
  Configured response headers are HSTS, `X-Content-Type-Options`,
  `X-Frame-Options`, `X-XSS-Protection`, and `Referrer-Policy`; a Content
  Security Policy is not configured by this list.
- **Tenant and privacy boundaries:** `family_id` isolates household records.
  `owner_id` provides within-family privacy only on supported models. Site
  administrators are distinct from household owners and must not be given
  access to household financial data by role checks.

## Production Requirements

Production startup validates a stable `SECRET_KEY` of at least 32 characters,
an application database URL, and a shared Redis `RATELIMIT_STORAGE_URI`
(`redis://` or `rediss://`). Do not use in-memory rate-limit storage in
production. Configure HTTPS, the actual trusted proxy count and addresses, and
the exact passkey origin/RP ID when passkeys are enabled. If outgoing email is
configured, set `APP_BASE_URL` to the public HTTPS origin.

Use the [production runbook](../deployment/README.md) for environment setup,
updates, backups, and recovery. Do not copy deployment commands from historical
SQLite-era guides.

## Operational Guidance

- Keep secrets, database files, and logs out of source control and public
  channels. Never publish a debugger PIN or a production secret.
- Do not enable Flask debug mode on a public interface.
- Keep PostgreSQL and Redis private to the application environment; do not
  expose them directly to the internet.
- Review application, reverse-proxy, and service logs through the approved
  operator workflow. Avoid copying personal or financial data into support
  requests.
- Use the repository test suite when changing authentication or privacy
  behavior:

  ```powershell
  venv\Scripts\python.exe -m pytest -q
  ```

## Related Documentation

- [Authentication setup](AUTHENTICATION_SETUP.md) describes passkeys, TOTP,
  invites, and session management.
- [Security best practices](SECURITY.md) covers development and deployment
  hygiene.
- [Production runbook](../deployment/README.md) is the operational source of
  truth.

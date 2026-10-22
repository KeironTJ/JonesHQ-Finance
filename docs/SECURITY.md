# Security Best Practices

This is operational guidance, not a security audit. For the controls implemented
in the application, see [Security Hardening](SECURITY_HARDENING.md) and
[Authentication Setup](AUTHENTICATION_SETUP.md). Production procedures are
documented in the [production runbook](../deployment/README.md).

## Historical Debugger Exposure

A development log previously showed that the Flask debugger had been enabled.
Treat any debugger PIN or secret that appeared in a log, screenshot, or support
message as exposed; this document intentionally does not reproduce it. Debug
mode is controlled by `FLASK_DEBUG` and defaults to off. Never enable the
interactive debugger on a public interface.

If you suspect unauthorized access, preserve relevant logs, rotate affected
credentials and secrets, invalidate sessions as appropriate, and follow the
production incident/recovery procedure. Restarting the server alone is not
proof that an exposure has been contained.

## Local Development

Use the repository launch scripts or bind Flask's development server only to
localhost. Enable debug mode only on a trusted local machine:

```powershell
$env:FLASK_DEBUG = "1"
flask run
```

Return to the normal non-debug configuration after local troubleshooting. Do
not use `--host 0.0.0.0` with debug mode enabled.

## Production Configuration

- Use the supported PostgreSQL configuration and a stable, randomly generated
  `SECRET_KEY` of at least 32 characters.
- Keep `FLASK_DEBUG` off and run the deployed service through the configured
  production server and service manager.
- Configure the shared Redis rate-limit backend, HTTPS, and trusted proxy
  settings according to the [production runbook](../deployment/README.md).
- Protect PostgreSQL, Redis, environment files, and backups from public access.
- Keep credentials out of source control. The repository ignores `.env`, local
  database files, and `instance/`; verify `git status` before committing.
- Review logs before sharing them. Redact credentials, session identifiers,
  personal details, and financial information.

Do not use SQLite recovery, `/home/joneshq/app` paths, or old Nginx/Certbot
procedures from the archived deployment guides.

## Response Headers and Sessions

The application configures HSTS, `X-Content-Type-Options`, `X-Frame-Options`,
`X-XSS-Protection`, and `Referrer-Policy`. Production cookies are Secure,
HttpOnly, and SameSite=Lax. Non-static application responses use
`Cache-Control: no-store`. See the security-control documentation for details
and the limits of these protections.

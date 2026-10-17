"""
Verify production settings and the Redis rate-limit backend.

Reads .env.production the same literal way systemd's EnvironmentFile does
(no shell expansion), builds the production app, and pings Redis.
Exits non-zero with a readable message if anything would stop the app starting.

Usage (from the app directory, as the app user):
    venv/bin/python deployment/check_production_config.py [path/to/.env.production]
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def load_env_file(path):
    values = {}
    with open(path, encoding='utf-8') as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            values[key.strip()] = value
    return values


def main():
    env_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJECT_ROOT, '.env.production')
    if not os.path.isfile(env_path):
        print(f"ERROR: {env_path} not found.")
        return 1

    env = load_env_file(env_path)
    problems = []
    secret = env.get('SECRET_KEY', '')
    if '$(' in secret or '`' in secret or ' ' in secret:
        problems.append(
            "SECRET_KEY looks like an unexpanded shell command, not a generated value. "
            "systemd does not run commands in env files. Run deployment/setup_redis.sh to replace it."
        )
    if not env.get('RATELIMIT_STORAGE_URI'):
        problems.append("RATELIMIT_STORAGE_URI is missing. Run deployment/setup_redis.sh.")
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}")
        return 1

    os.environ.update(env)
    os.chdir(PROJECT_ROOT)
    sys.path.insert(0, PROJECT_ROOT)
    try:
        from app import create_app
        from extensions import limiter

        app = create_app('production')
        with app.app_context():
            if not limiter.storage.check():
                raise RuntimeError("Redis did not respond to a health check.")
    except Exception as error:  # report any startup failure in plain terms
        print(f"ERROR: Production configuration check failed: {error}")
        return 1

    print("OK: production configuration is valid and Redis is reachable.")
    print(f"    Rate-limit storage: {env['RATELIMIT_STORAGE_URI']}")
    print(f"    Trusted proxies:    {env.get('TRUSTED_PROXY_COUNT', '0')}")
    if env.get('TRUSTED_PROXY_IPS', '').strip():
        print(f"    Proxy addresses:    {env['TRUSTED_PROXY_IPS']} (other direct connections get 403)")
    elif env.get('TRUSTED_PROXY_COUNT', '0') not in ('', '0'):
        print("    WARNING: TRUSTED_PROXY_IPS is not set. Any host that can reach port 8000 can "
              "bypass HTTPS and spoof its IP. Set it to the proxy's IP address.")
    if app.config.get('MAIL_SERVER'):
        print(f"    Email:              {app.config['MAIL_SERVER']}:{app.config['MAIL_PORT']} "
              f"from {app.config['MAIL_FROM']}")
        print(f"    Links point at:     {app.config['APP_BASE_URL']}")
        print("    Send a test with:   flask email test you@example.com")
    else:
        print("    Email:              off (password reset by email and security alerts disabled)")
    return 0


if __name__ == '__main__':
    sys.exit(main())

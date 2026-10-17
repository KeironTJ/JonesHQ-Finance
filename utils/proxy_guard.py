"""Accept traffic only from the trusted reverse proxy (and loopback).

With TRUSTED_PROXY_IPS set, forwarded headers (client IP, https) are honoured
only on connections from those addresses. Loopback connections (local health
checks) are served but their forwarded headers are ignored. Any other direct
connection gets 403, so LAN clients can't bypass HTTPS or spoof their IP to
dodge rate limits.
"""
from ipaddress import ip_address, ip_network

from werkzeug.middleware.proxy_fix import ProxyFix


def parse_proxy_networks(value):
    """Parse a comma-separated list of IPs/CIDRs. Raises ValueError on bad entries."""
    networks = []
    for item in (value or '').split(','):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ip_network(item, strict=False))
        except ValueError:
            raise ValueError(f"TRUSTED_PROXY_IPS contains an invalid address: {item!r}") from None
    return networks


def _client_address(environ):
    try:
        address = ip_address((environ.get('REMOTE_ADDR') or '').strip())
    except ValueError:
        return None
    return getattr(address, 'ipv4_mapped', None) or address


def _forbidden(start_response):
    body = b'Direct access is not allowed. Use the public address.\n'
    start_response('403 Forbidden', [
        ('Content-Type', 'text/plain; charset=utf-8'),
        ('Content-Length', str(len(body))),
    ])
    return [body]


class TrustedProxyMiddleware:
    def __init__(self, app, proxy_networks, proxy_count):
        self.direct_app = app
        self.proxied_app = ProxyFix(app, x_for=proxy_count, x_proto=proxy_count, x_host=0) if proxy_count else app
        self.proxy_networks = list(proxy_networks)

    def __call__(self, environ, start_response):
        address = _client_address(environ)
        if address is not None and any(address in network for network in self.proxy_networks):
            return self.proxied_app(environ, start_response)
        if address is not None and address.is_loopback:
            return self.direct_app(environ, start_response)
        return _forbidden(start_response)


def wrap_wsgi_app(app):
    """Install the proxy handling configured in app.config onto app.wsgi_app."""
    count = app.config['TRUSTED_PROXY_COUNT']
    networks = parse_proxy_networks(app.config.get('TRUSTED_PROXY_IPS'))
    if networks:
        app.wsgi_app = TrustedProxyMiddleware(app.wsgi_app, networks, count)
    elif count:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=count, x_proto=count, x_host=0)

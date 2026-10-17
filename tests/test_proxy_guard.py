import pytest
from flask import Flask, jsonify, request

from utils.proxy_guard import parse_proxy_networks, wrap_wsgi_app


def make_app(proxy_count=1, proxy_ips=''):
    app = Flask(__name__)
    app.config.update(TRUSTED_PROXY_COUNT=proxy_count, TRUSTED_PROXY_IPS=proxy_ips)

    @app.route('/whoami')
    def whoami():
        return jsonify(ip=request.remote_addr, scheme=request.scheme)

    wrap_wsgi_app(app)
    return app.test_client()


FORWARDED = {'X-Forwarded-For': '203.0.113.9', 'X-Forwarded-Proto': 'https'}


def get(client, remote_addr):
    return client.get('/whoami', headers=FORWARDED, environ_base={'REMOTE_ADDR': remote_addr})


def test_trusted_proxy_forwarded_headers_are_honoured():
    client = make_app(proxy_ips='192.168.1.50')
    response = get(client, '192.168.1.50')
    assert response.status_code == 200
    assert response.json == {'ip': '203.0.113.9', 'scheme': 'https'}


def test_cidr_entries_match():
    client = make_app(proxy_ips='10.0.0.0/24, 192.168.1.50')
    assert get(client, '10.0.0.7').json['ip'] == '203.0.113.9'


def test_other_direct_clients_are_rejected():
    client = make_app(proxy_ips='192.168.1.50')
    response = get(client, '192.168.1.77')
    assert response.status_code == 403
    assert b'Direct access is not allowed' in response.data


def test_loopback_is_served_without_trusting_forwarded_headers():
    client = make_app(proxy_ips='192.168.1.50')
    response = get(client, '127.0.0.1')
    assert response.status_code == 200
    assert response.json == {'ip': '127.0.0.1', 'scheme': 'http'}


def test_ipv4_mapped_proxy_address_matches():
    client = make_app(proxy_ips='192.168.1.50')
    assert get(client, '::ffff:192.168.1.50').status_code == 200


def test_missing_remote_address_is_rejected():
    client = make_app(proxy_ips='192.168.1.50')
    assert get(client, '').status_code == 403


def test_without_proxy_ips_existing_behaviour_is_kept():
    client = make_app(proxy_ips='')
    response = get(client, '192.168.1.77')
    assert response.status_code == 200
    assert response.json['ip'] == '203.0.113.9'

    untrusting = make_app(proxy_count=0, proxy_ips='')
    assert get(untrusting, '192.168.1.77').json['ip'] == '192.168.1.77'


def test_invalid_proxy_ip_is_rejected():
    with pytest.raises(ValueError, match='TRUSTED_PROXY_IPS'):
        parse_proxy_networks('192.168.1.50, not-an-ip')

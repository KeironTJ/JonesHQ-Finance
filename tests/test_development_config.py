import os
import subprocess
import sys

import pytest
from flask import Flask

from config import DevelopmentConfig, ProductionConfig, TestingConfig


def development_app(instance_path):
    app = Flask(__name__, instance_path=str(instance_path))
    app.config.from_object(DevelopmentConfig)
    app.config['SECRET_KEY'] = None
    DevelopmentConfig.init_app(app)
    return app


def test_development_key_survives_process_restart(tmp_path):
    first = development_app(tmp_path)
    serializer = first.session_interface.get_signing_serializer(first)
    cookie = serializer.dumps({'_user_id': '1:session-token', '_fresh': True})
    script = (
        'import sys; from flask import Flask; from config import DevelopmentConfig; '
        'app = Flask(__name__, instance_path=sys.argv[1]); '
        'app.config.from_object(DevelopmentConfig); app.config["SECRET_KEY"] = None; '
        'DevelopmentConfig.init_app(app); '
        'data = app.session_interface.get_signing_serializer(app).loads(sys.argv[2]); '
        'assert data == {"_user_id": "1:session-token", "_fresh": True}'
    )
    subprocess.run(
        [sys.executable, '-c', script, str(tmp_path), cookie],
        check=True, capture_output=True, text=True,
    )
    key_path = tmp_path / 'development_secret_key'
    assert key_path.read_text(encoding='ascii') == first.config['SECRET_KEY']
    if os.name != 'nt':
        assert key_path.stat().st_mode & 0o777 == 0o600


def test_development_creates_instance_directory(tmp_path):
    instance_path = tmp_path / 'instance'
    app = development_app(instance_path)
    assert len(app.config['SECRET_KEY']) == 64
    assert (instance_path / 'development_secret_key').is_file()


def test_explicit_development_key_takes_precedence(tmp_path):
    app = Flask(__name__, instance_path=str(tmp_path))
    app.config.from_object(DevelopmentConfig)
    app.config['SECRET_KEY'] = 'explicit-test-secret'
    DevelopmentConfig.init_app(app)
    assert app.config['SECRET_KEY'] == 'explicit-test-secret'
    assert not (tmp_path / 'development_secret_key').exists()


@pytest.mark.parametrize('key', ['', 'short', 'z' * 64])
def test_invalid_development_key_fails_explicitly(tmp_path, key):
    (tmp_path / 'development_secret_key').write_text(key, encoding='ascii')
    with pytest.raises(ValueError, match='Invalid local development key'):
        development_app(tmp_path)


def test_unreadable_development_key_is_not_replaced(tmp_path):
    (tmp_path / 'development_secret_key').mkdir()
    with pytest.raises(OSError):
        development_app(tmp_path)


def test_production_still_requires_explicit_secret(tmp_path):
    development_app(tmp_path)
    app = Flask(__name__, instance_path=str(tmp_path))
    app.config.from_object(ProductionConfig)
    app.config['SECRET_KEY'] = None
    with pytest.raises(ValueError, match='SECRET_KEY environment variable must be set'):
        ProductionConfig.init_app(app)


def test_testing_does_not_create_development_key(tmp_path):
    app = Flask(__name__, instance_path=str(tmp_path))
    app.config.from_object(TestingConfig)
    TestingConfig.init_app(app)
    assert app.config['SECRET_KEY'] == 'test-only-secret-key'
    assert not (tmp_path / 'development_secret_key').exists()

import os
import pytest
import json, toml
from confy.loader import Config
from confy.exceptions import MissingMandatoryConfig

@pytest.fixture
def json_cfg(tmp_path):
    data = {"auth": {"local": {"enabled": False}}}
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(data))
    return str(path)

@pytest.fixture
def toml_cfg(tmp_path):
    data = {"auth": {"local": {"enabled": False}}}
    path = tmp_path / "cfg.toml"
    path.write_text(toml.dumps(data))
    return str(path)

def test_load_json(json_cfg):
    cfg = Config(file_path=json_cfg)
    assert cfg.auth.local.enabled is False

def test_load_toml(toml_cfg):
    cfg = Config(file_path=toml_cfg)
    assert cfg.auth.local.enabled is False

def test_env_override(monkeypatch, json_cfg):
    monkeypatch.setenv('APP_CONF_auth_local_enabled'.upper(), 'true')
    cfg = Config(file_path=json_cfg, prefix='APP_CONF')
    assert cfg.auth.local.enabled is True

def test_dict_override(json_cfg):
    overrides = {"auth.local.enabled": True}
    cfg = Config(file_path=json_cfg, overrides_dict=overrides)
    assert cfg.auth.local.enabled is True

def test_defaults_and_mandatory():
    with pytest.raises(MissingMandatoryConfig):
        Config(defaults={'db': {}}, mandatory=['db.host'])
    cfg = Config(defaults={'db': {'host': '127.0.0.1'}},
                 mandatory=['db.host'])
    assert cfg.db.host == '127.0.0.1'

# tests/test_loader.py
import copy
import json
import logging  # Import logging
import os
from pathlib import Path

import pytest

# Configure logging for tests to see confy debug messages
# logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(name)s:%(message)s')

# Use tomllib if available (Python 3.11+), otherwise try tomli
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

# Ensure python-dotenv is available for .env tests
try:
    from dotenv import find_dotenv

    # Function to explicitly clear dotenv's loaded state if possible
    def clear_dotenv_state():
        try:
            # Attempt to clear find_dotenv cache if it exists
            cache = getattr(find_dotenv, "cache", None)
            if cache:
                cache.clear()
                logging.debug("Cleared find_dotenv cache.")
        except Exception as e:
            logging.warning(f"Could not clear find_dotenv cache: {e}")
        # Note: Removing vars from os.environ is tricky as we don't know
        # exactly which ones were loaded by a previous dotenv call.
        # Relying on monkeypatch.delenv is generally safer in tests.
        pass

    dotenv_available = True
except ImportError:
    dotenv_available = False

    def clear_dotenv_state():
        pass


from confy.exceptions import MissingMandatoryConfig
from confy.loader import Config, get_by_dot, set_by_dot

# --- Fixtures ---


@pytest.fixture
def defaults_data():
    """Default configuration data."""
    return {
        "database": {"host": "localhost", "port": 5432, "user": "default_user"},
        "logging": {"level": "INFO", "file": None},
        "feature_flags": {"new_ui": False, "beta_feature": False},
        "list_items": [1, {"a": 10}, 3],  # Default list item 'a' is 10
    }


@pytest.fixture
def json_cfg_path(tmp_path):
    """Create a sample JSON config file."""
    data = {
        "database": {"host": "json.db.example.com", "port": 5433},
        "logging": {"level": "DEBUG"},
        "new_section": {"key": "json_value"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    logging.debug(f"Created JSON config at: {path}")
    return str(path)


@pytest.fixture
def toml_cfg_path(tmp_path):
    """Create a sample TOML config file."""
    if not tomllib:
        pytest.skip("tomli/tomllib not installed")
    toml_content = """
[database]
host = "toml.db.example.com"
port = 5434
[logging]
level = "WARNING"
[new_section]
key = "toml_value"
# List replacement test: 'a' should be 20 here
list_items = [ 1, { a = 20 }, 3 ]
    """
    path = tmp_path / "config.toml"
    path.write_text(toml_content, encoding="utf-8")
    logging.debug(f"Created TOML config at: {path}")
    return str(path)


@pytest.fixture
def dotenv_file_path(tmp_path):
    """Create a sample .env file."""
    if not dotenv_available:
        pytest.skip("python-dotenv not installed")
    content = """
# Sample .env file for testing
MYAPP_DATABASE_USER="dotenv_user"
MYAPP_LOGGING_FILE="/var/log/app.log"
MYAPP_FEATURE_FLAGS_BETA_FEATURE=true
MYAPP_SECRETS_API_KEY="dotenv_key_123"
EXISTING_VAR=dotenv_value
OTHER_VAR=ignore_me
MYAPP_DATABASE_PORT=5555
MYAPP_FEATURE_FLAGS_NEW_UI=false # Explicit false for testing override/parsing
    """
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    logging.debug(f"Created .env file at: {path}")
    clear_dotenv_state()  # Clear any cached state before returning path
    return str(path)


# --- Helper to ensure clean env before specific tests ---
def ensure_clean_env(monkeypatch, *var_names):
    """Explicitly delete specific env vars before a test using monkeypatch."""
    logging.debug(f"Cleaning env vars: {var_names}")
    for var in var_names:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def manage_test_environment(monkeypatch):
    """
    Uses monkeypatch for setup/teardown of env vars and current directory.
    Ensures a clean state for each test.
    """

    original_cwd = os.getcwd()
    logging.debug(f"Original CWD: {original_cwd}")

    yield  # Run the test

    # Monkeypatch handles reverting changes made via its methods (setenv, delenv, chdir).
    # Additional cleanup:
    # 1. Clear dotenv state as an extra precaution.
    if dotenv_available:
        clear_dotenv_state()
        logging.debug("Cleared dotenv state post-test.")

    # 2. Restore CWD just in case monkeypatch didn't (it should).
    if os.getcwd() != original_cwd:
        logging.warning(
            f"CWD mismatch after test ({os.getcwd()}), restoring to {original_cwd}"
        )
        os.chdir(original_cwd)

    # 3. Optionally remove environment variables added during the test
    #    that weren't explicitly managed by monkeypatch.delenv.
    # current_keys = set(os.environ.keys())
    # added_keys = current_keys - original_environ_keys
    # if added_keys:
    #     logging.debug(f"Removing potentially added env vars: {added_keys}")
    #     for key in added_keys:
    #         monkeypatch.delenv(key, raising=False) # Use monkeypatch for final cleanup too


# --- Test Cases ---


def test_load_defaults_only(defaults_data):
    """Test loading only from the defaults dictionary."""
    logging.debug("Running test_load_defaults_only")
    cfg = Config(defaults=defaults_data)
    assert cfg.database.host == "localhost"
    assert cfg.database.port == 5432
    assert cfg.logging.level == "INFO"
    assert cfg.feature_flags.new_ui is False
    assert isinstance(cfg.database, Config)
    assert isinstance(cfg.list_items, list)
    assert isinstance(cfg.list_items[1], Config)
    assert cfg.list_items[1].a == 10  # Check default list item value


def test_load_json_over_defaults(defaults_data, json_cfg_path):
    """Test JSON file values overriding defaults."""
    logging.debug("Running test_load_json_over_defaults")
    cfg = Config(defaults=defaults_data, file_path=json_cfg_path)
    assert cfg.database.host == "json.db.example.com"  # Overridden by JSON
    assert cfg.database.port == 5433  # Overridden by JSON
    assert cfg.logging.level == "DEBUG"  # Overridden by JSON
    assert cfg.new_section.key == "json_value"  # Added by JSON
    assert cfg.database.user == "default_user"  # From defaults (not in JSON)
    assert cfg.feature_flags.new_ui is False  # From defaults
    assert isinstance(cfg.database, Config)
    assert isinstance(cfg.new_section, Config)


def test_load_toml_over_defaults(defaults_data, toml_cfg_path):
    """Test TOML file values overriding defaults, including list replacement."""
    logging.debug("Running test_load_toml_over_defaults")
    cfg = Config(defaults=defaults_data, file_path=toml_cfg_path)
    assert cfg.database.host == "toml.db.example.com"  # Overridden by TOML
    assert cfg.database.port == 5434  # Overridden by TOML
    assert cfg.logging.level == "WARNING"  # Overridden by TOML
    assert cfg.new_section.key == "toml_value"  # Added by TOML
    assert cfg.database.user == "default_user"  # From defaults
    assert cfg.feature_flags.new_ui is False  # From defaults

    # Check list replacement worked: TOML list should replace default list
    assert isinstance(cfg.list_items, list)
    assert len(cfg.list_items) == 3
    assert cfg.list_items[0] == 1
    assert isinstance(cfg.list_items[1], Config)  # Item should be wrapped
    assert (
        cfg.list_items[1].a == 20
    )  # Value should be 20 from TOML (was 10 in defaults)
    assert cfg.list_items[2] == 3
    assert isinstance(cfg.database, Config)
    assert isinstance(cfg.new_section, Config)


def test_load_env_over_file_and_defaults(defaults_data, json_cfg_path, monkeypatch):
    """Test environment variables overriding file and defaults."""
    logging.debug("Running test_load_env_over_file_and_defaults")
    # Ensure clean slate for vars being set
    ensure_clean_env(
        monkeypatch,
        "MYAPP_DATABASE_HOST",
        "MYAPP_DATABASE_PORT",
        "MYAPP_LOGGING_LEVEL",
        "MYAPP_FEATURE_FLAGS_NEW_UI",
        "MYAPP_NEW_SECTION_KEY",
        "MYAPP_ADDED_BY_ENV",
    )

    # Set environment variables
    monkeypatch.setenv("MYAPP_DATABASE_HOST", "env.db.example.com")
    monkeypatch.setenv("MYAPP_DATABASE_PORT", "6000")  # String number -> int
    monkeypatch.setenv("MYAPP_LOGGING_LEVEL", "TRACE")
    monkeypatch.setenv(
        "MYAPP_FEATURE_FLAGS_NEW_UI", "true"
    )  # String "true" -> bool True
    monkeypatch.setenv("MYAPP_NEW_SECTION_KEY", "env_value")
    monkeypatch.setenv("MYAPP_ADDED_BY_ENV", "env_only")

    # Initialize Config, disable .env loading for this test
    cfg = Config(
        defaults=defaults_data,
        file_path=json_cfg_path,
        prefix="MYAPP",
        load_dotenv_file=False,
    )

    # Assert values based on precedence: env > file > defaults
    assert cfg.database.host == "env.db.example.com"  # From env
    assert cfg.database.port == 6000  # From env (parsed as int)
    assert cfg.logging.level == "TRACE"  # From env
    assert cfg.feature_flags.new_ui is True  # From env (parsed as bool)
    assert cfg.new_section.key == "env_value"  # From env (overrides file)
    assert cfg.added_by_env == "env_only"  # Added by env
    assert cfg.database.user == "default_user"  # From defaults (not in file or env)
    assert isinstance(cfg.feature_flags, Config)


def test_load_dotenv_implicitly(defaults_data, dotenv_file_path, monkeypatch):
    """Test implicit loading of .env file when found in current/parent dir."""
    if not dotenv_available:
        pytest.skip("python-dotenv required")
    logging.debug("Running test_load_dotenv_implicitly")
    # Ensure clean slate for vars potentially loaded from .env
    ensure_clean_env(
        monkeypatch,
        "MYAPP_DATABASE_USER",
        "MYAPP_DATABASE_PORT",
        "MYAPP_LOGGING_FILE",
        "MYAPP_FEATURE_FLAGS_BETA_FEATURE",
        "MYAPP_FEATURE_FLAGS_NEW_UI",
        "MYAPP_SECRETS_API_KEY",
        "EXISTING_VAR",
        "OTHER_VAR",
    )

    # Change directory to where the .env file is located
    dotenv_dir = Path(dotenv_file_path).parent
    monkeypatch.chdir(dotenv_dir)
    logging.debug(f"Changed CWD to: {dotenv_dir}")

    # Initialize Config with prefix, implicit .env loading enabled
    cfg = Config(defaults=defaults_data, prefix="MYAPP", load_dotenv_file=True)

    # Assert values based on precedence: .env (via env) > defaults
    assert cfg.database.user == "dotenv_user"  # From .env
    assert cfg.logging.file == "/var/log/app.log"  # From .env
    assert cfg.feature_flags.beta_feature is True  # From .env ("true" -> True)
    assert cfg.secrets.api_key == "dotenv_key_123"  # From .env
    assert cfg.database.port == 5555  # From .env (parsed as int)
    assert cfg.feature_flags.new_ui is False  # From .env ("false" -> False)

    # Check values not overridden by .env remain from defaults
    assert cfg.database.host == "localhost"  # Default remains
    assert cfg.logging.level == "INFO"  # Default remains

    # Check that other vars from .env are loaded into os.environ but not into Config (due to prefix)
    assert os.environ.get("EXISTING_VAR") == "dotenv_value"
    assert os.environ.get("OTHER_VAR") == "ignore_me"
    assert "existing_var" not in cfg  # Not matching prefix
    assert "other_var" not in cfg  # Not matching prefix
    assert isinstance(cfg.secrets, Config)


def test_load_dotenv_explicitly(defaults_data, dotenv_file_path, monkeypatch):
    """Test loading .env file from an explicit path."""
    if not dotenv_available:
        pytest.skip("python-dotenv required")
    logging.debug("Running test_load_dotenv_explicitly")
    # Ensure clean slate
    ensure_clean_env(
        monkeypatch,
        "MYAPP_DATABASE_USER",
        "MYAPP_DATABASE_PORT",
        "MYAPP_LOGGING_FILE",
        "MYAPP_FEATURE_FLAGS_BETA_FEATURE",
        "MYAPP_FEATURE_FLAGS_NEW_UI",
        "MYAPP_SECRETS_API_KEY",
    )

    # Initialize Config with prefix and explicit dotenv_path
    cfg = Config(
        defaults=defaults_data,
        prefix="MYAPP",
        load_dotenv_file=True,
        dotenv_path=dotenv_file_path,
    )

    # Assert values are loaded from the specified .env file
    assert cfg.database.user == "dotenv_user"
    assert cfg.logging.file == "/var/log/app.log"
    assert cfg.feature_flags.beta_feature is True  # From .env ("true" -> True)
    assert cfg.secrets.api_key == "dotenv_key_123"
    assert cfg.database.port == 5555  # From .env
    assert cfg.feature_flags.new_ui is False  # From .env ("false" -> False)

    # Check defaults remain where not overridden
    assert cfg.database.host == "localhost"


def test_load_dotenv_disabled(defaults_data, dotenv_file_path, monkeypatch):
    """Test that .env file is NOT loaded when load_dotenv_file=False."""
    logging.debug("Running test_load_dotenv_disabled")
    # Ensure clean slate
    ensure_clean_env(
        monkeypatch,
        "MYAPP_DATABASE_USER",
        "MYAPP_DATABASE_PORT",
        "MYAPP_LOGGING_FILE",
        "MYAPP_FEATURE_FLAGS_BETA_FEATURE",
        "MYAPP_SECRETS_API_KEY",
    )
    # We might even set a conflicting env var manually to be sure .env isn't loaded later
    monkeypatch.setenv("SOME_OTHER_VAR", "test_value")
    # Change to the directory containing .env, but loading should still be skipped
    monkeypatch.chdir(Path(dotenv_file_path).parent)

    # Initialize Config with loading disabled
    cfg = Config(defaults=defaults_data, prefix="MYAPP", load_dotenv_file=False)

    # Assert that values ONLY come from defaults, not the .env file
    assert cfg.database.user == "default_user"  # Should be default
    assert cfg.logging.file is None  # Should be default
    assert cfg.feature_flags.beta_feature is False  # Should be default
    assert "secrets" not in cfg  # Should not be added from .env
    assert cfg.database.port == 5432  # Should be default


def test_dotenv_does_not_override_existing_env(
    defaults_data, dotenv_file_path, monkeypatch
):
    """Test that dotenv.load_dotenv(override=False) behavior is respected."""
    if not dotenv_available:
        pytest.skip("python-dotenv required")
    logging.debug("Running test_dotenv_does_not_override_existing_env")
    # Ensure clean slate for the specific vars we'll preset
    ensure_clean_env(
        monkeypatch, "MYAPP_DATABASE_USER", "MYAPP_DATABASE_PORT", "EXISTING_VAR"
    )

    # Pre-set environment variables *before* Config initialization (and .env loading)
    monkeypatch.setenv("EXISTING_VAR", "preset_value")
    monkeypatch.setenv("MYAPP_DATABASE_USER", "preset_user")  # This conflicts with .env
    monkeypatch.setenv(
        "MYAPP_DATABASE_PORT", "9999"
    )  # This conflicts with .env (as string)

    # Change to the directory containing .env
    monkeypatch.chdir(Path(dotenv_file_path).parent)

    # Initialize Config, .env loading is enabled (default)
    cfg = Config(defaults=defaults_data, prefix="MYAPP", load_dotenv_file=True)

    # Assert that pre-existing env vars were NOT overridden by .env
    assert os.environ["EXISTING_VAR"] == "preset_value"  # Env var itself wasn't changed
    assert (
        cfg.database.user == "preset_user"
    )  # Value comes from preset env var, not .env
    assert (
        cfg.database.port == 9999
    )  # Value comes from preset env var (parsed as int), not .env

    # Assert that other variables *only* present in .env *were* loaded
    assert cfg.logging.file == "/var/log/app.log"
    assert cfg.feature_flags.beta_feature is True


def test_overrides_dict_highest_precedence(defaults_data, json_cfg_path, monkeypatch):
    """Test that overrides_dict takes the highest precedence."""
    logging.debug("Running test_overrides_dict_highest_precedence")
    # Ensure clean slate for env vars
    ensure_clean_env(
        monkeypatch,
        "MYAPP_DATABASE_HOST",
        "MYAPP_DATABASE_PORT",
        "MYAPP_LOGGING_LEVEL",
        "MYAPP_DATABASE_USER",
    )

    # Set some environment variables (lower precedence than overrides_dict)
    monkeypatch.setenv("MYAPP_DATABASE_HOST", "env.db.example.com")
    monkeypatch.setenv("MYAPP_DATABASE_PORT", "6000")  # Env var
    monkeypatch.setenv("MYAPP_LOGGING_LEVEL", "DEBUG")  # Env var

    # Define the overrides dictionary
    overrides = {
        "database.host": "override.db.example.com",  # Override env, file, default
        "logging.level": '"TRACE"',  # Override env, file, default (JSON string -> string)
        "feature_flags.new_ui": "false",  # Override default (string "false" -> bool False)
        "database.user": "override_user",  # Override default
        "added_by_override": 123,  # Add new value
    }

    # Initialize Config with all sources, explicitly disable .env loading
    cfg = Config(
        defaults=defaults_data,
        file_path=json_cfg_path,
        prefix="MYAPP",
        overrides_dict=overrides,
        load_dotenv_file=False,
    )

    # Assert values based on precedence: overrides > env > file > defaults
    assert cfg.database.host == "override.db.example.com"  # From overrides
    assert cfg.logging.level == "TRACE"  # From overrides (parsed as string)
    assert cfg.feature_flags.new_ui is False  # From overrides (parsed as bool)
    assert cfg.database.user == "override_user"  # From overrides
    assert cfg.added_by_override == 123  # From overrides
    assert cfg.database.port == 6000  # From env (not in overrides)
    assert cfg.new_section.key == "json_value"  # From file (not in env or overrides)


# --- Remaining tests ---


def test_mandatory_keys_present(defaults_data):
    """Test that no error is raised if all mandatory keys are present."""
    logging.debug("Running test_mandatory_keys_present")
    mandatory = ["database.host", "logging.level", "feature_flags.new_ui"]
    try:
        cfg = Config(defaults=defaults_data, mandatory=mandatory)
        # Basic check to ensure config loaded
        assert cfg.database.host == "localhost"
    except MissingMandatoryConfig:
        pytest.fail("MissingMandatoryConfig raised unexpectedly")


def test_mandatory_keys_missing(defaults_data):
    """Test that MissingMandatoryConfig is raised with the correct missing keys."""
    logging.debug("Running test_mandatory_keys_missing")
    mandatory = [
        "database.host",
        "logging.level",
        "secrets.api_key",
    ]  # secrets.api_key is missing
    with pytest.raises(MissingMandatoryConfig) as excinfo:
        Config(defaults=defaults_data, mandatory=mandatory)
    assert "secrets.api_key" in excinfo.value.missing_keys
    assert len(excinfo.value.missing_keys) == 1


def test_mandatory_keys_invalid_path(defaults_data):
    """Test mandatory check failure when path is invalid (accesses non-dict)."""
    logging.debug("Running test_mandatory_keys_invalid_path")
    mandatory = [
        "database.host",
        "logging.level.sublevel",
    ]  # logging.level is not a dict
    with pytest.raises(MissingMandatoryConfig) as excinfo:
        Config(defaults=defaults_data, mandatory=mandatory)
    assert "logging.level.sublevel" in excinfo.value.missing_keys


def test_attribute_access(defaults_data):
    """Test basic attribute-style access."""
    logging.debug("Running test_attribute_access")
    cfg = Config(defaults=defaults_data)
    assert cfg.database.host == "localhost"
    assert cfg.logging.level == "INFO"
    assert cfg.feature_flags.new_ui is False
    # Access nested Config object
    db_config = cfg.database
    assert isinstance(db_config, Config)
    assert db_config.port == 5432


def test_attribute_access_missing_key(defaults_data):
    """Test that AttributeError is raised for non-existent keys."""
    logging.debug("Running test_attribute_access_missing_key")
    cfg = Config(defaults=defaults_data)
    with pytest.raises(AttributeError):
        _ = cfg.non_existent_key
    with pytest.raises(AttributeError):
        _ = cfg.database.non_existent_sub_key


def test_get_method(defaults_data):
    """Test the .get() method for safe access with defaults."""
    logging.debug("Running test_get_method")
    cfg = Config(defaults=defaults_data)
    # Existing keys
    assert cfg.get("database.host") == "localhost"
    assert cfg.get("logging.level") == "INFO"
    # Missing key with default
    assert cfg.get("database.password", "default_pw") == "default_pw"
    # Missing key without default
    assert cfg.get("secrets.api_key") is None
    # Invalid path with default
    assert cfg.get("logging.level.invalid", "fallback") == "fallback"
    # Invalid path without default
    assert cfg.get("logging.level.invalid") is None


def test_contains_check(defaults_data):
    """Test the 'in' operator with dot-notation."""
    logging.debug("Running test_contains_check")
    cfg = Config(defaults=defaults_data)
    # Top level and nested keys
    assert "database" in cfg
    assert "database.host" in cfg
    assert "logging.level" in cfg
    assert "feature_flags.new_ui" in cfg
    # Non-existent keys/paths
    assert "non_existent_key" not in cfg
    assert "database.password" not in cfg
    assert "logging.level.invalid" not in cfg


def test_set_attribute(defaults_data):
    """Test setting attributes using dot-notation and direct assignment."""
    logging.debug("Running test_set_attribute")
    cfg = Config(defaults=defaults_data)
    # Modify existing values
    cfg.database.host = "new.host.com"
    cfg.logging.level = "ERROR"
    cfg.feature_flags.beta_feature = True
    # Add a new nested structure (should be wrapped)
    cfg.new_top_level = {"a": 1, "b": {"c": 2}}

    # Verify changes
    assert cfg.database.host == "new.host.com"
    assert cfg.logging.level == "ERROR"
    assert cfg.feature_flags.beta_feature is True
    # Check underlying dict access still works
    assert cfg["feature_flags"]["beta_feature"] is True

    # Verify wrapping of new structure
    assert isinstance(cfg.new_top_level, Config)
    assert cfg.new_top_level.a == 1
    assert isinstance(cfg.new_top_level.b, Config)
    assert cfg.new_top_level.b.c == 2


def test_del_attribute(defaults_data):
    """Test deleting attributes using dot-notation."""
    logging.debug("Running test_del_attribute")
    cfg = Config(
        copy.deepcopy(defaults_data)
    )  # Use deep copy to avoid modifying fixture
    # Delete nested attribute
    del cfg.logging.level
    assert "level" not in cfg.logging
    # Delete top-level attribute
    del cfg.database
    assert "database" not in cfg
    # Test deleting non-existent attribute
    with pytest.raises(AttributeError):
        del cfg.non_existent


def test_as_dict(defaults_data, json_cfg_path):
    """Test converting the Config object back to a plain dictionary."""
    logging.debug("Running test_as_dict")
    cfg = Config(defaults=defaults_data, file_path=json_cfg_path)
    plain_dict = cfg.as_dict()

    # Check types recursively
    assert isinstance(plain_dict, dict)
    assert not isinstance(plain_dict, Config)
    assert isinstance(plain_dict["database"], dict)
    assert not isinstance(plain_dict["database"], Config)
    assert isinstance(plain_dict["new_section"], dict)
    assert not isinstance(plain_dict["new_section"], Config)
    assert isinstance(plain_dict["list_items"], list)
    assert isinstance(plain_dict["list_items"][1], dict)  # Item in list should be dict
    assert not isinstance(plain_dict["list_items"][1], Config)

    # Check values
    assert plain_dict["database"]["host"] == "json.db.example.com"
    assert plain_dict["logging"]["level"] == "DEBUG"
    assert plain_dict["feature_flags"]["new_ui"] is False
    assert (
        plain_dict["list_items"][1]["a"] == 10
    )  # From defaults, as JSON didn't override list


def test_list_handling_wrapping(defaults_data, toml_cfg_path):
    """Test list replacement and wrapping of dicts within lists."""
    logging.debug("Running test_list_handling_wrapping")
    # Defaults list_items[1].a is 10
    # TOML list_items[1].a is 20
    cfg = Config(defaults=defaults_data, file_path=toml_cfg_path)

    # Check list was replaced by TOML's list
    assert isinstance(cfg.list_items, list)
    assert cfg.list_items[0] == 1
    list_dict_item = cfg.list_items[1]
    assert isinstance(list_dict_item, Config)  # Item should be wrapped
    assert list_dict_item.a == 20  # Value should be 20 from TOML
    assert cfg.list_items[2] == 3

    # Test setting a new list with nested dicts
    cfg.new_list = ["x", {"y": 100, "z": {"zz": 200}}, "w"]
    assert isinstance(cfg.new_list, list)
    assert isinstance(cfg.new_list[1], Config)
    assert cfg.new_list[1].y == 100
    assert isinstance(cfg.new_list[1].z, Config)
    assert cfg.new_list[1].z.zz == 200


def test_empty_prefix(monkeypatch):
    """Test using an empty string prefix ('') to load unprefixed env vars."""
    logging.debug("Running test_empty_prefix")
    ensure_clean_env(
        monkeypatch, "DATABASE_HOST", "LOGGING_LEVEL", "UNDERSCORE_VAR_TEST"
    )
    monkeypatch.setenv("DATABASE_HOST", "env.host")
    monkeypatch.setenv("LOGGING_LEVEL", "INFO")
    monkeypatch.setenv(
        "UNDERSCORE_VAR_TEST", "value"
    )  # Should become underscore.var.test

    cfg = Config(prefix="", load_dotenv_file=False)  # prefix="" means match all

    assert cfg.database.host == "env.host"
    assert cfg.logging.level == "INFO"
    assert cfg.underscore.var.test == "value"


def test_no_prefix(monkeypatch):
    """Test using prefix=None (default) disables env var loading based on prefix."""
    logging.debug("Running test_no_prefix")
    ensure_clean_env(monkeypatch, "DATABASE_HOST")
    monkeypatch.setenv("DATABASE_HOST", "env.host")  # Set an env var

    # Initialize with prefix=None (default)
    cfg = Config(
        prefix=None, defaults={"database": {"host": "default"}}, load_dotenv_file=False
    )

    # Env var should NOT be loaded as prefix matching is off
    assert cfg.database.host == "default"


def test_malformed_file(tmp_path):
    """Test handling of malformed JSON and TOML files."""
    logging.debug("Running test_malformed_file")
    # Malformed JSON
    json_path = tmp_path / "bad.json"
    json_path.write_text(
        "{ database: { host: invalid }", encoding="utf-8"
    )  # Invalid JSON syntax
    with pytest.raises(RuntimeError) as excinfo_json:
        Config(file_path=str(json_path))
    assert "Error loading/parsing file" in str(excinfo_json.value)

    # Malformed TOML
    if tomllib:
        toml_path = tmp_path / "bad.toml"
        toml_path.write_text(
            '[database\nhost = "missing_quote', encoding="utf-8"
        )  # Invalid TOML syntax
        with pytest.raises(RuntimeError) as excinfo_toml:
            Config(file_path=str(toml_path))
        # Check for common TOML parsing error messages
        assert "Error loading/parsing file" in str(excinfo_toml.value)


def test_file_not_found():
    """Test FileNotFoundError when config file doesn't exist."""
    logging.debug("Running test_file_not_found")
    with pytest.raises(FileNotFoundError):
        Config(file_path="/path/to/non/existent/file.json")


def test_private_attribute_access(defaults_data):
    """Test that access to attributes starting with '_' raises AttributeError."""
    logging.debug("Running test_private_attribute_access")
    cfg = Config(defaults=defaults_data)
    # Attempting to get private/magic methods should fail via __getattr__
    with pytest.raises(AttributeError):
        _ = cfg._internal_method
    with pytest.raises(AttributeError):
        _ = cfg.__private_var
    # Attempting to delete private attributes should fail via __delattr__
    with pytest.raises(AttributeError):
        del cfg._some_internal


# --- Helper function tests ---
def test_get_by_dot_helper():
    """Test the get_by_dot helper function directly."""
    logging.debug("Running test_get_by_dot_helper")
    data = {"a": 1, "b": {"c": 2, "d": {"e": 3}}, "f": [0, {"g": 1}]}
    cfg = Config(data)  # Wrap in Config for consistent access testing
    # Valid paths
    assert get_by_dot(cfg, "a") == 1
    assert get_by_dot(cfg, "b.c") == 2
    assert get_by_dot(cfg, "b.d.e") == 3
    # Invalid paths
    with pytest.raises(
        TypeError, match="Cannot access key 'x' on non-dictionary item at path 'a'"
    ):
        get_by_dot(cfg, "a.x")  # 'a' is an int
    with pytest.raises(KeyError, match="Key path 'b.x' not found"):
        get_by_dot(cfg, "b.x")  # 'x' doesn't exist under 'b'
    with pytest.raises(KeyError, match="Key path 'b.d.f' not found"):
        get_by_dot(cfg, "b.d.f")  # 'f' doesn't exist under 'b.d'
    with pytest.raises(
        TypeError, match="Cannot access key 'g' on non-dictionary item at path 'f'"
    ):
        get_by_dot(cfg, "f.g")  # 'f' is a list


def test_set_by_dot_helper():
    """Test the set_by_dot helper function directly."""
    logging.debug("Running test_set_by_dot_helper")
    data = {}
    # Set top-level
    set_by_dot(data, "a", 1)
    assert data["a"] == 1
    # Set nested (creates intermediate dict)
    set_by_dot(data, "b.c", 2)
    assert data["b"]["c"] == 2
    # Set deeper nested (creates intermediate dicts)
    set_by_dot(data, "b.d.e", 3)
    assert data["b"]["d"]["e"] == 3
    # Overwrite existing value
    set_by_dot(data, "b.c", 99)
    assert data["b"]["c"] == 99
    # Overwrite non-dict with dict (should work, logs warning in Config context)
    set_by_dot(data, "a.f", 4)  # 'a' was 1, now becomes {'f': 4}
    assert isinstance(data["a"], dict)
    assert data["a"]["f"] == 4

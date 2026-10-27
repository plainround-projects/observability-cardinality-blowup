import pytest

from cardinality_lab.infrastructure.settings import AppSettings, SettingsError


def test_defaults_are_the_safe_baseline():
    settings = AppSettings.from_env({})
    assert settings.metrics_include_user_id is False
    assert settings.slow_tenant == ""
    assert (settings.port, settings.metrics_port, settings.bind_host) == (8080, 9100, "127.0.0.1")
    assert settings.seed is None


def test_the_experiment_switches_are_read():
    settings = AppSettings.from_env(
        {"METRICS_INCLUDE_USER_ID": "TRUE", "SLOW_TENANT": "tenant-0007", "SEED": "9", "SLOW_SECONDS": "3"}
    )
    assert settings.metrics_include_user_id is True
    assert (settings.slow_tenant, settings.seed, settings.slow_seconds) == ("tenant-0007", 9, 3.0)


@pytest.mark.parametrize(
    "env",
    [
        {"METRICS_INCLUDE_USER_ID": "yes"},
        {"DECLINED_RATE": "2"},
        {"APP_PORT": "http"},
        {"SLOW_SECONDS": "-1"},
        {"LOG_LEVEL": "LOUD"},
    ],
)
def test_invalid_values_are_rejected(env):
    with pytest.raises(SettingsError):
        AppSettings.from_env(env)

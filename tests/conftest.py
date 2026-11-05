import pytest

from fixflow.agent import FixFlowAgent
from fixflow.config import Settings
from fixflow.tools import Store


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    monkeypatch.setenv("FIXFLOW_PROVIDER", "offline")


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def store(settings):
    return Store(":memory:", settings.devices_csv)


@pytest.fixture
def agent(settings, store):
    return FixFlowAgent(settings, store=store)

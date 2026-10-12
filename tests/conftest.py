import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: needs Chrome")

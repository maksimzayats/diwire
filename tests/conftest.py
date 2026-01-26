"""Shared pytest fixtures for diwire tests."""

import pytest

from diwire.container import Container
from diwire.dependencies import DependenciesExtractor
from diwire.types import Lifetime


@pytest.fixture()
def container() -> Container:
    """Default container with auto-registration enabled."""
    return Container(register_if_missing=True)


@pytest.fixture()
def container_no_autoregister() -> Container:
    """Container with register_if_missing=False."""
    return Container(register_if_missing=False)


@pytest.fixture()
def container_singleton() -> Container:
    """Container with lifetime singleton as default."""
    return Container(
        register_if_missing=True,
        autoregister_default_lifetime=Lifetime.SINGLETON,
    )


@pytest.fixture()
def dependencies_extractor() -> DependenciesExtractor:
    """DependenciesExtractor instance."""
    return DependenciesExtractor()

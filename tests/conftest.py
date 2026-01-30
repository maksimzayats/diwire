"""Shared pytest fixtures for diwire tests."""

import pytest

from diwire.container import Container
from diwire.dependencies import DependenciesExtractor
from diwire.types import Lifetime


@pytest.fixture()
def container() -> Container:
    """Default container with auto-registration enabled."""
    return Container(autoregister=True)


@pytest.fixture()
def container_no_autoregister() -> Container:
    """Container with autoregister=False."""
    return Container(autoregister=False)


@pytest.fixture()
def container_singleton() -> Container:
    """Container with lifetime singleton as default."""
    return Container(
        autoregister=True,
        autoregister_default_lifetime=Lifetime.SINGLETON,
    )


@pytest.fixture()
def dependencies_extractor() -> DependenciesExtractor:
    """DependenciesExtractor instance."""
    return DependenciesExtractor()

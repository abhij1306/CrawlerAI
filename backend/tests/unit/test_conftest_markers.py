"""Opt-out markers for the heavy autouse fixtures (audit 4.14).

The suite-wide autouse fixtures in ``tests/conftest.py`` stub public DNS
resolution and install a FakeRedis client; 1,700+ tests implicitly depend on
those defaults. The ``real_dns`` / ``real_redis`` markers let an individual
test opt back into the real wiring. These tests pin both directions: stubbed
by default, real when marked.
"""

from __future__ import annotations

import pytest

import app.core.redis as app_redis
import app.core.url_safety as url_safety
from tests.conftest import FakeRedis

pytestmark = pytest.mark.unit

# Bound at import time, before any fixture runs: the module's own resolver.
_ORIGINAL_RESOLVE_HOST_IPS = url_safety._resolve_host_ips


def test_dns_resolution_is_stubbed_by_default() -> None:
    assert url_safety._resolve_host_ips is not _ORIGINAL_RESOLVE_HOST_IPS


@pytest.mark.real_dns
def test_real_dns_marker_keeps_the_original_resolver() -> None:
    assert url_safety._resolve_host_ips is _ORIGINAL_RESOLVE_HOST_IPS


def test_redis_is_faked_by_default(fake_redis: FakeRedis) -> None:
    assert isinstance(fake_redis, FakeRedis)
    assert app_redis._client is fake_redis


@pytest.mark.real_redis
async def test_real_redis_marker_skips_the_fake(
    fake_redis: FakeRedis | None,
) -> None:
    assert fake_redis is None
    client = app_redis.get_redis()
    try:
        assert not isinstance(client, FakeRedis)
        try:
            await client.ping()
        except Exception:
            pytest.skip("no real Redis server available")
    finally:
        # Do not leak a real client/pool into module state for later tests.
        await app_redis.close_redis()

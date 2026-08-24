"""test_browser_context cases split by public behavior."""

from __future__ import annotations

from tests.component.browser_context_test_support import (
    AsyncSession,
    DomainCookieMemory,
    async_sessionmaker,
    browser_identity,
    cookie_store,
    host_protection_memory,
    pytest,
    uuid4,
)
from app.core.security import hash_password
from app.models.user import User


@pytest.fixture(autouse=True)
async def _default_cookie_owner(monkeypatch: pytest.MonkeyPatch, test_user):
    for name in (
        "persist_storage_state_for_domain",
        "load_storage_state_for_domain",
        "list_domain_cookie_memory",
        "export_cookie_header_for_domain",
    ):
        original = getattr(cookie_store, name)

        async def _owned(*args, __original=original, **kwargs):
            kwargs.setdefault("user_id", test_user.id)
            return await __original(*args, **kwargs)

        monkeypatch.setattr(cookie_store, name, _owned)
    return test_user.id


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_cookie_memory_isolated_between_users(
    db_session,
    test_user,
) -> None:
    second_user = User(
        email=f"cookie-isolation-{uuid4().hex}@example.com",
        hashed_password=hash_password("password123"),
        role="user",
    )
    db_session.add(second_user)
    await db_session.flush()
    domain = f"shared-{uuid4().hex}.example.com"

    for user, value in ((test_user, "first-secret"), (second_user, "second-secret")):
        assert await cookie_store.persist_storage_state_for_domain(
            domain,
            {
                "cookies": [
                    {
                        "name": "session",
                        "value": value,
                        "domain": domain,
                        "path": "/",
                    }
                ],
                "origins": [],
            },
            session=db_session,
            user_id=user.id,
        )

    first = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        user_id=test_user.id,
    )
    second = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        user_id=second_user.id,
    )

    assert first is not None and first["cookies"][0]["value"] == "first-secret"
    assert second is not None and second["cookies"][0]["value"] == "second-secret"


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_commits_owned_session(
    db_session,
    monkeypatch,
) -> None:
    session_factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    monkeypatch.setattr(cookie_store, "SessionLocal", session_factory)
    domain = f"owned-session-{uuid4().hex}.example.com"
    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
    )

    rows = await cookie_store.list_domain_cookie_memory(domain)

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["domain"] == domain


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_persists_test_domains(
    db_session,
) -> None:
    domain = f"owned-session-{uuid4().hex}.example.test"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["domain"] == domain
    assert loaded is not None


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_strips_null_bytes(db_session) -> None:
    domain = f"null-byte-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc\x00def",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": f"https://{domain}",
                    "localStorage": [
                        {"name": "cart", "value": '{"id":"123\x00"}'},
                    ],
                }
            ],
        },
        session=db_session,
    )

    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert saved is True
    assert loaded is not None
    assert loaded["cookies"][0]["value"] == "abcdef"
    assert loaded["origins"] == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_keeps_engine_specific_rows(
    db_session,
) -> None:
    domain = f"engine-scoped-{uuid4().hex}.example.com"

    chromium_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "chromium-session",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="chromium",
    )
    real_chrome_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "real-chrome-session",
                    "value": "2",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="real_chrome",
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    chromium_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="chromium",
    )
    real_chrome_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="real_chrome",
    )

    assert chromium_saved is True
    assert real_chrome_saved is True
    assert len(rows) == 2
    assert {str(row["browser_engine"]) for row in rows} == {"chromium", "real_chrome"}
    assert chromium_state == {
        "cookies": [
            {
                "name": "chromium-session",
                "value": "1",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }
    assert real_chrome_state == {
        "cookies": [
            {
                "name": "real-chrome-session",
                "value": "2",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_persists_localhost_with_port(
    db_session,
) -> None:
    domain = "http://localhost:3001/products/widget"

    saved = await cookie_store.persist_storage_state_for_domain(
        domain,
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": "localhost",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(
        "localhost:3001", session=db_session
    )
    all_rows = await cookie_store.list_domain_cookie_memory(session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(
        "localhost:3001", session=db_session
    )

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["domain"] == "localhost:3001"
    assert any(row["domain"] == "localhost:3001" for row in all_rows)
    assert loaded is not None


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_accepts_iterable_storage_rows(
    db_session,
) -> None:
    domain = f"iterable-state-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": (
                {
                    "name": "session",
                    "value": "abc",
                    "domain": f".{domain}",
                    "path": "/",
                },
            ),
            "origins": (
                {
                    "origin": f"https://{domain}",
                    "localStorage": ({"name": "consent", "value": "accepted"},),
                },
            ),
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["cookie_count"] == 1
    assert rows[0]["origin_count"] == 0
    assert loaded == {
        "cookies": [
            {
                "name": "session",
                "value": "abc",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_export_cookie_header_for_domain_dedupes_cookie_names(
    db_session,
) -> None:
    domain = f"handoff-cookie-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "root",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "session",
                    "value": "product",
                    "domain": f".{domain}",
                    "path": "/products",
                },
                {
                    "name": "_px3",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "consent",
                    "value": "yes",
                    "domain": f".{domain}",
                    "path": "/",
                },
            ],
            "origins": [
                {
                    "origin": f"https://{domain}",
                    "localStorage": [{"name": "consent", "value": "accepted"}],
                }
            ],
        },
        session=db_session,
        browser_engine="real_chrome",
    )

    header = await cookie_store.export_cookie_header_for_domain(
        f"https://{domain}/products/widget",
        session=db_session,
        browser_engine="real_chrome",
    )

    assert saved is True
    assert header == "session=product; consent=yes"


@pytest.mark.asyncio
@pytest.mark.component
async def test_export_cookie_header_for_domain_does_not_match_path_prefixes(
    db_session,
) -> None:
    domain = f"path-prefix-{uuid4().hex}.example.com"

    await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/foo",
        {
            "cookies": [
                {
                    "name": "prefix-only",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/foo",
                },
                {
                    "name": "nested",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/foo/bar",
                },
            ],
            "origins": [],
        },
        session=db_session,
    )

    header = await cookie_store.export_cookie_header_for_domain(
        f"https://{domain}/foobar",
        session=db_session,
    )

    assert header is None


def test_http_cookie_export_does_not_send_secure_cookie_over_http() -> None:
    state = {
        "cookies": [
            {
                "name": "secure-session",
                "value": "secret",
                "domain": ".example.com",
                "path": "/",
                "secure": True,
            },
            {
                "name": "preference",
                "value": "dark",
                "domain": ".example.com",
                "path": "/",
            },
        ]
    }

    assert cookie_store.http_cookie_pairs_for_url("http://example.com/", state) == [
        ("preference", "dark")
    ]
    assert cookie_store.http_cookie_pairs_for_url("https://example.com/", state) == [
        ("secure-session", "secret"),
        ("preference", "dark"),
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_keeps_patchright_isolated(
    db_session,
) -> None:
    domain = f"patchright-engine-{uuid4().hex}.example.com"

    chromium_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "chromium-session",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="chromium",
    )
    patchright_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "patchright-session",
                    "value": "2",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="patchright",
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    chromium_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="chromium",
    )
    patchright_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="patchright",
    )

    assert chromium_saved is True
    assert patchright_saved is True
    assert len(rows) == 2
    assert {str(row["browser_engine"]) for row in rows} == {"chromium", "patchright"}
    assert chromium_state == {
        "cookies": [
            {
                "name": "chromium-session",
                "value": "1",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }
    assert patchright_state == {
        "cookies": [
            {
                "name": "patchright-session",
                "value": "2",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_host_protection_policy_tracks_patchright_as_browser_lane(
    db_session,
) -> None:
    url = f"https://patchright-policy-{uuid4().hex}.example.com/products/widget"

    blocked_policy = await host_protection_memory.note_host_hard_block(
        url,
        method="browser:patchright",
        session=db_session,
    )
    success_policy = await host_protection_memory.note_host_usable_fetch(
        url,
        method="browser:patchright",
        session=db_session,
    )

    assert blocked_policy.request_blocked is False
    assert blocked_policy.patchright_blocked is True
    assert blocked_policy.last_block_method == "browser:patchright"
    assert success_policy.patchright_success is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_host_protection_policy_maps_legacy_browser_block_to_patchright(
    db_session,
) -> None:
    url = f"https://legacy-browser-policy-{uuid4().hex}.example.com/products/widget"

    blocked_policy = await host_protection_memory.note_host_hard_block(
        url,
        method="browser",
        session=db_session,
    )

    assert blocked_policy.request_blocked is False
    assert blocked_policy.patchright_blocked is True
    assert blocked_policy.last_block_method == "browser"


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_storage_state_for_domain_filters_existing_challenge_state(
    db_session,
    _default_cookie_owner,
) -> None:
    domain = f"poisoned-{uuid4().hex}.example.com"
    db_session.add(
        DomainCookieMemory(
            user_id=_default_cookie_owner,
            domain=domain,
            storage_state=cookie_store._encrypt_storage_state(
                {
                    "cookies": [
                        {
                            "name": "_pxvid",
                            "value": "challenge",
                            "domain": f".{domain}",
                            "path": "/",
                        },
                        {
                            "name": "session",
                            "value": "safe",
                            "domain": f".{domain}",
                            "path": "/",
                        },
                        {
                            "name": "datadome",
                            "value": "challenge-token",
                            "domain": f".{domain}",
                            "path": "/",
                        },
                        {
                            "name": "_abck",
                            "value": "akamai-token",
                            "domain": f".{domain}",
                            "path": "/",
                        },
                        {
                            "name": "__cf_bm",
                            "value": "cloudflare-token",
                            "domain": f".{domain}",
                            "path": "/",
                        },
                        {
                            "name": "analytics",
                            "value": "bot_management:captcha",
                            "domain": f".{domain}",
                            "path": "/",
                        },
                    ],
                    "origins": [
                        {
                            "origin": f"https://{domain}",
                            "localStorage": [
                                {"name": "PXapp_px_hvd", "value": "challenge"},
                                {"name": "safe-key", "value": "datadome blocked"},
                                {"name": "consent", "value": "accepted"},
                            ],
                        }
                    ],
                }
            ),
            state_fingerprint="poisoned",
        )
    )
    await db_session.commit()

    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert loaded == {
        "cookies": [
            {
                "name": "session",
                "value": "safe",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_list_domain_cookie_memory_counts_stored_entries(
    db_session,
    _default_cookie_owner,
) -> None:
    domain = f"stored-count-{uuid4().hex}.example.com"
    db_session.add(
        DomainCookieMemory(
            user_id=_default_cookie_owner,
            domain=domain,
            storage_state=cookie_store._encrypt_storage_state(
                {
                    "cookies": [
                        {
                            "name": "session",
                            "value": "safe",
                            "domain": f".{domain}",
                            "path": "/",
                        },
                        "legacy-cookie-row",
                    ],
                    "origins": [
                        {"origin": f"https://{domain}", "localStorage": []},
                        "legacy-origin-row",
                    ],
                }
            ),
            state_fingerprint="stored-count",
        )
    )
    await db_session.commit()

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)

    assert rows[0]["cookie_count"] == 2
    assert rows[0]["origin_count"] == 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_rejects_challenge_only_state(
    db_session,
) -> None:
    domain = f"challenge-only-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "_px2",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "pxcts",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "datadome",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
            ],
            "origins": [
                {
                    "origin": f"https://{domain}",
                    "localStorage": [
                        {"name": "PXapp_px_fp", "value": "challenge"},
                        {"name": "safe-key", "value": "captcha page"},
                    ],
                }
            ],
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert saved is False
    assert rows == []
    assert loaded is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_storage_state_for_domain_drops_origin_shell_when_local_storage_filters_empty(
    db_session,
    _default_cookie_owner,
) -> None:
    domain = f"origin-shell-{uuid4().hex}.example.com"
    db_session.add(
        DomainCookieMemory(
            user_id=_default_cookie_owner,
            domain=domain,
            storage_state=cookie_store._encrypt_storage_state(
                {
                    "cookies": [
                        {
                            "name": "session",
                            "value": "safe",
                            "domain": f".{domain}",
                            "path": "/",
                        }
                    ],
                    "origins": [
                        {
                            "origin": f"https://{domain}",
                            "localStorage": [
                                {"name": "PXapp_px_fp", "value": "challenge"},
                            ],
                        }
                    ],
                }
            ),
            state_fingerprint="origin-shell",
        )
    )
    await db_session.commit()

    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert loaded == {
        "cookies": [
            {
                "name": "session",
                "value": "safe",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.component
class TestNativeContextContract:
    """Verify that the native browser identity emits a clean Playwright context."""

    def test_native_context_deheadlessifies_user_agent(self) -> None:
        # Headless Chromium leaks a "HeadlessChrome" UA token that bot-defense
        # vendors block on sight. The context UA must present as plain Chrome.
        opts = browser_identity.build_playwright_context_spec(
            browser_major_version=145
        ).context_options
        user_agent = str(opts.get("user_agent") or "")
        assert "HeadlessChrome" not in user_agent
        assert "Chrome/145" in user_agent

    def test_native_context_emits_coherent_client_hints(self) -> None:
        opts = browser_identity.build_playwright_context_spec(
            browser_major_version=145
        ).context_options
        headers = opts.get("extra_http_headers") or {}
        assert headers.get("sec-ch-ua-mobile") == "?0"
        assert "Google Chrome" in str(headers.get("sec-ch-ua") or "")
        assert '"145"' in str(headers.get("sec-ch-ua") or "")

    def test_native_context_merges_locality_headers_with_client_hints(self) -> None:
        opts = browser_identity.build_playwright_context_spec(
            browser_major_version=145,
            locality_profile={
                "browser_context_profile": {
                    "extra_http_headers": {"Accept-Language": "en-US"}
                }
            },
        ).context_options
        headers = opts.get("extra_http_headers") or {}
        assert headers["Accept-Language"] == "en-US"
        assert headers.get("sec-ch-ua-mobile") == "?0"
        assert "Google Chrome" in str(headers.get("sec-ch-ua") or "")

    @pytest.mark.parametrize(
        "geolocation",
        (
            {"latitude": "north", "longitude": 12.5},
            {"latitude": 48.1, "longitude": object()},
            {"latitude": 48.1, "longitude": 12.5, "accuracy": "exact"},
            {"latitude": "nan", "longitude": 12.5},
            {"latitude": 91, "longitude": 12.5},
            {"latitude": 48.1, "longitude": 181},
            {"latitude": 48.1, "longitude": 12.5, "accuracy": -1},
        ),
    )
    def test_native_context_ignores_invalid_geolocation(
        self, geolocation: dict[str, object]
    ) -> None:
        opts = browser_identity.build_playwright_context_spec(
            locality_profile={"geolocation": geolocation}
        ).context_options

        assert "geolocation" not in opts

    def test_native_context_copies_permissions_before_adding_geolocation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        native_permissions = ["camera"]
        monkeypatch.setattr(
            browser_identity,
            "NATIVE_REAL_CHROME_CONTEXT_OPTIONS",
            {"no_viewport": True, "permissions": native_permissions},
        )

        opts = browser_identity.build_playwright_context_spec(
            locality_profile={"geolocation": {"latitude": 48.1, "longitude": 12.5}}
        ).context_options

        assert opts["permissions"] == ["camera", "geolocation"]
        assert native_permissions == ["camera"]

    def test_native_context_uses_no_viewport_true(self) -> None:
        opts = browser_identity.build_playwright_context_spec().context_options
        assert opts.get("no_viewport") is True

    def test_native_context_has_no_init_script(self) -> None:
        spec = browser_identity.build_playwright_context_spec()
        assert spec.init_script is None

    def test_clear_browser_identity_cache_is_noop(self) -> None:
        browser_identity.clear_browser_identity_cache()

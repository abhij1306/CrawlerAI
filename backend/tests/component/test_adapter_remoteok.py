from __future__ import annotations

import pytest

from app.services.adapters import remoteok as remoteok_module
from app.services.adapters.remoteok import RemoteOkAdapter




@pytest.mark.component
def test_remoteok_adapter_swallows_json_decode_errors() -> None:
    assert RemoteOkAdapter()._extract_remoteok_from_html("<html>not json</html>") == []


@pytest.mark.component
def test_remoteok_adapter_does_not_swallow_unrelated_value_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_value_error(_value: object) -> object:
        raise ValueError("parser bug")

    monkeypatch.setattr(remoteok_module.json, "loads", raise_value_error)

    with pytest.raises(ValueError, match="parser bug"):
        RemoteOkAdapter()._extract_remoteok_from_html("[]")


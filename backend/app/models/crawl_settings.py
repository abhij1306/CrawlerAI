from __future__ import annotations
# pylint: disable=missing-function-docstring

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.models.crawl_settings_views import (
    AcquisitionContractView,
    ProxySettingsView,
    RunExecutionView,
    RunProfileView,
)

if TYPE_CHECKING:
    # Type-only edge: the acquisition plan contract is owned by
    # app/acquisition/runtime_plan.py (canonical-contract owner allowlist) and is
    # imported lazily inside acquisition_plan() so the models layer holds no
    # runtime import from acquisition/extraction.
    from app.acquisition.runtime_plan import AcquisitionIntent


@dataclass(slots=True)
class CrawlRunSettings:
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: object) -> CrawlRunSettings:
        if isinstance(value, Mapping):
            return cls(dict(value))
        return cls({})

    @property
    def _execution(self) -> RunExecutionView:
        return RunExecutionView(self.data)

    @property
    def _proxy(self) -> ProxySettingsView:
        return ProxySettingsView(self.data)

    @property
    def _contract(self) -> AcquisitionContractView:
        return AcquisitionContractView(self.data)

    @property
    def _profile(self) -> RunProfileView:
        return RunProfileView(self.data)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.data

    def with_updates(self, **updates: Any) -> CrawlRunSettings:
        merged = dict(self.data)
        merged.update(updates)
        return CrawlRunSettings(merged)

    def urls(self) -> list[str]:
        return self._execution.urls()

    def traversal_mode(self) -> str | None:
        return self._execution.traversal_mode()

    def advanced_enabled(self) -> bool:
        return self._execution.advanced_enabled()

    def respect_robots_txt(self) -> bool:
        return self._execution.respect_robots_txt()

    def max_pages(self) -> int:
        return self._execution.max_pages()

    def max_records(self) -> int:
        return self._execution.max_records()

    def max_scrolls(self) -> int:
        return self._execution.max_scrolls()

    def sleep_ms(self) -> int:
        return self._execution.sleep_ms()

    def url_batch_concurrency(self) -> int:
        return self._execution.url_batch_concurrency()

    def url_timeout_seconds(self) -> float:
        return self._execution.url_timeout_seconds()

    def fetch_profile(self) -> dict[str, object]:
        return self._execution.fetch_profile()

    def proxy_list(self) -> list[str]:
        return self._proxy.proxy_list()

    def proxy_profile(self, *, infer_rotation: bool = True) -> dict[str, object]:
        return self._proxy.proxy_profile(infer_rotation=infer_rotation)

    def acquisition_contract(self) -> dict[str, object]:
        return self._contract.acquisition_contract()

    def locality_profile(self) -> dict[str, object]:
        return self._profile.locality_profile()

    def diagnostics_profile(self) -> dict[str, object]:
        return self._profile.diagnostics_profile()

    def acquisition_profile(self) -> dict[str, object]:
        return self._profile.acquisition_profile()

    def normalized_for_storage(self) -> dict[str, Any]:
        return self._profile.normalized_for_storage()

    def llm_enabled(self) -> bool:
        return bool(self.data.get("llm_enabled"))

    def llm_config_snapshot(self) -> dict[str, Any]:
        snapshot = self.data.get("llm_config_snapshot")
        return dict(snapshot) if isinstance(snapshot, Mapping) else {}

    def extraction_contract(self) -> list[dict[str, Any]]:
        rows = self.data.get("extraction_contract")
        if not isinstance(rows, Sequence) or isinstance(rows, str):
            return []
        return [dict(row) for row in rows if isinstance(row, Mapping)]

    def acquisition_plan(
        self,
        *,
        surface: str,
        max_records: int | None = None,
    ) -> AcquisitionIntent:
        # Deferred imports: AcquisitionIntent/parse_surface are owned by the
        # acquisition/extraction layers (see app/acquisition/runtime_plan.py and
        # app/extraction/surfaces.py); module-level imports there would violate
        # models-layer ownership. Runtime behavior is unchanged.
        from app.acquisition.runtime_plan import AcquisitionIntent
        from app.extraction.surfaces import parse_surface

        normalized_surface = parse_surface(surface).value
        return AcquisitionIntent(
            surface=normalized_surface,
            proxy_list=tuple(self.proxy_list()),
            traversal_mode=self.traversal_mode(),
            max_pages=self.max_pages(),
            max_scrolls=self.max_scrolls(),
            max_records=max_records if max_records is not None else self.max_records(),
            sleep_ms=self.sleep_ms(),
        )


def normalize_crawl_settings(value: object) -> dict[str, Any]:
    return CrawlRunSettings.from_value(value).normalized_for_storage()

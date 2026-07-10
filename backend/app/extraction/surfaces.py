from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Surface(str, Enum):
    ECOMMERCE_LISTING = "ecommerce_listing"
    ECOMMERCE_DETAIL = "ecommerce_detail"
    JOB_LISTING = "job_listing"
    JOB_DETAIL = "job_detail"


@dataclass(frozen=True)
class SurfaceSpec:
    surface: Surface
    domain: Literal["commerce", "jobs"]
    cardinality: Literal["one", "many"]
    root_entity: Literal["product", "job"]
    required_facts: frozenset[str]
    allowed_facts: frozenset[str]
    supports_variants: bool
    supports_traversal: bool
    structured_types: frozenset[str] = frozenset()
    listing_optional_text_facts: tuple[str, ...] = ()
    listing_structured_fact_kinds: tuple[tuple[str, str], ...] = ()
    listing_network_fact_keys: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class ListingSchema:
    """Typed listing lens derived from one canonical ``SurfaceSpec``."""

    surface: Surface
    root_entity: str
    title_fact: str
    url_fact: str
    optional_text_facts: tuple[str, ...]
    structured_types: frozenset[str]
    structured_fact_kinds: tuple[tuple[str, str], ...]
    network_fact_keys: tuple[tuple[str, tuple[str, ...]], ...]
    network_identity_keys: tuple[str, ...]

    @property
    def bindable_facts(self) -> tuple[str, ...]:
        return (self.title_fact, *self.optional_text_facts)

    def entity_type_for(self, fact_type: str) -> str:
        return fact_type.split(".", 1)[0]


COMMERCE_FACTS = frozenset(
    {
        "product.url",
        "product.title",
        "product.brand",
        "product.description",
        "product.category",
        "product.sku",
        "product.mpn",
        "product.gtin",
        "product.material",
        "product.color",
        "product.size",
        "variant.id",
        "variant.url",
        "variant.sku",
        "variant.gtin",
        "variant.selected",
        "offer.price",
        "offer.currency",
        "offer.original_price",
        "offer.availability",
        "offer.stock_quantity",
        "offer.seller",
        "asset.url",
        "asset.role",
    }
)

JOB_FACTS = frozenset(
    {
        "job.url",
        "job.title",
        "job.id",
        "job.company",
        "job.location",
        "job.salary",
        "job.type",
        "job.posted_date",
        "job.apply_url",
        "job.description",
        "job.requirements",
        "job.responsibilities",
        "job.qualifications",
        "job.benefits",
        "job.skills",
        "job.remote",
        "job.department",
    }
)

SURFACE_SPECS: dict[Surface, SurfaceSpec] = {
    Surface.ECOMMERCE_DETAIL: SurfaceSpec(
        surface=Surface.ECOMMERCE_DETAIL,
        domain="commerce",
        cardinality="one",
        root_entity="product",
        required_facts=frozenset({"product.url", "product.title"}),
        allowed_facts=COMMERCE_FACTS,
        supports_variants=True,
        supports_traversal=False,
        structured_types=frozenset({"Product"}),
    ),
    Surface.ECOMMERCE_LISTING: SurfaceSpec(
        surface=Surface.ECOMMERCE_LISTING,
        domain="commerce",
        cardinality="many",
        root_entity="product",
        required_facts=frozenset({"product.url", "product.title"}),
        allowed_facts=COMMERCE_FACTS,
        supports_variants=False,
        supports_traversal=True,
        structured_types=frozenset({"Product", "ItemList"}),
        listing_optional_text_facts=("offer.price",),
        listing_structured_fact_kinds=(
            ("product.title", "name_or_title"),
            ("product.url", "url"),
            ("offer.price", "offer_price"),
            ("asset.image_url", "image"),
        ),
        listing_network_fact_keys=(
            ("product.title", ("name", "title", "productName")),
            ("product.url", ("url", "href", "link", "productUrl", "pdpUrl")),
            ("offer.price", ("price", "salePrice", "currentPrice", "amount")),
        ),
    ),
    Surface.JOB_DETAIL: SurfaceSpec(
        surface=Surface.JOB_DETAIL,
        domain="jobs",
        cardinality="one",
        root_entity="job",
        required_facts=frozenset({"job.title"}),
        allowed_facts=JOB_FACTS,
        supports_variants=False,
        supports_traversal=False,
        structured_types=frozenset({"JobPosting"}),
    ),
    Surface.JOB_LISTING: SurfaceSpec(
        surface=Surface.JOB_LISTING,
        domain="jobs",
        cardinality="many",
        root_entity="job",
        required_facts=frozenset({"job.url", "job.title"}),
        allowed_facts=JOB_FACTS,
        supports_variants=False,
        supports_traversal=True,
        structured_types=frozenset({"JobPosting", "ItemList"}),
        listing_optional_text_facts=("job.company", "job.location"),
        listing_structured_fact_kinds=(
            ("job.title", "name_or_title"),
            ("job.url", "url"),
            ("job.company", "organization"),
            ("job.location", "location"),
        ),
        listing_network_fact_keys=(
            ("job.title", ("title", "name", "jobTitle")),
            ("job.url", ("url", "href", "link", "jobUrl", "applyUrl")),
            ("job.id", ("id", "jobId", "opportunityId", "requisitionId")),
            ("job.company", ("company", "companyName", "organization")),
            ("job.location", ("location", "locationName", "city")),
        ),
    ),
}


def parse_surface(value: object) -> Surface:
    text = str(value or "").strip().lower()
    try:
        return Surface(text)
    except ValueError as exc:
        allowed = ", ".join(surface.value for surface in Surface)
        raise ValueError(f"surface must be one of: {allowed}") from exc


def surface_spec(value: Surface | str) -> SurfaceSpec:
    surface = value if isinstance(value, Surface) else parse_surface(value)
    return SURFACE_SPECS[surface]


def listing_schema(value: Surface | str) -> ListingSchema | None:
    """Return the listing contract, or ``None`` for one-record surfaces."""
    spec = surface_spec(value)
    if spec.cardinality != "many":
        return None
    title_fact = next(
        (fact for fact in spec.required_facts if fact.endswith(".title")), ""
    )
    url_fact = next((fact for fact in spec.required_facts if fact.endswith(".url")), "")
    if not title_fact or not url_fact:
        return None
    return ListingSchema(
        surface=spec.surface,
        root_entity=spec.root_entity,
        title_fact=title_fact,
        url_fact=url_fact,
        optional_text_facts=tuple(
            fact
            for fact in spec.listing_optional_text_facts
            if fact in spec.allowed_facts
        ),
        structured_types=spec.structured_types,
        structured_fact_kinds=spec.listing_structured_fact_kinds,
        network_fact_keys=spec.listing_network_fact_keys,
        network_identity_keys=(
            "id",
            "jobId",
            "opportunityId",
            "requisitionId",
        )
        if spec.surface is Surface.JOB_LISTING
        else (),
    )


def structured_type_selectors(value: Surface | str) -> tuple[str, ...]:
    """DOM structured-type probes derived from the canonical surface schema."""
    return tuple(
        f'[itemtype*="{schema_type}" i]'
        for schema_type in sorted(surface_spec(value).structured_types)
        if schema_type != "ItemList"
    )


def public_surface_for_internal(value: Surface | str) -> str:
    surface = surface_spec(value).surface
    if surface is Surface.ECOMMERCE_DETAIL:
        return "ecommerce"
    return surface.value

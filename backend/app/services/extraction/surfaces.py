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


def public_surface_for_internal(value: Surface | str) -> str:
    return surface_spec(value).surface.value

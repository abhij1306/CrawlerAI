from __future__ import annotations

ECOMMERCE_DETAIL_PATH_MARKERS: tuple[str, ...] = (
    "/dp/",
    "/p/",
    "/pd/",
    "/spd/",
    "/proddetail/",
    "/productpage",
    "/product",
    "/products/",
    "/item/",
    "/produit/",
    "/produits/",
    "/produkt/",
    "/produkte/",
    "/producto/",
    "/productos/",
    "/prodotto/",
    "/prodotti/",
    "/seihin/",
    "/shohin/",
    "/artikel/",
    "/articulo/",
    "/merchandise/",
    "/goods/",
    "/sku/",
    "/detail/",
    "/buy/",
)

JOB_DETAIL_PATH_MARKERS: tuple[str, ...] = (
    "/job",
    "/jobs",
    "/career",
    "/careers",
    "/position",
    "/posting",
    "/opening",
    "/viewjob",
    "showjob=",
    "/emploi/",
    "/offres-demploi/",
    "/stelle/",
    "/stellenangebot/",
    "/empleo/",
    "/ofertas-de-empleo/",
    "/lavoro/",
    "/offerte-di-lavoro/",
    "/kyuujin/",
    "/shigoto/",
    "/vacancy/",
    "/vacatures/",
    "/recruitment/",
)


def detail_path_markers(surface: str) -> tuple[str, ...]:
    selected = str(surface or "").strip().lower()
    if selected in {"ecommerce_detail", "ecommerce_listing"}:
        return ECOMMERCE_DETAIL_PATH_MARKERS
    if selected in {"job_detail", "job_listing"}:
        return JOB_DETAIL_PATH_MARKERS
    return ()


def all_detail_path_markers() -> tuple[str, ...]:
    return tuple(
        dict.fromkeys((*ECOMMERCE_DETAIL_PATH_MARKERS, *JOB_DETAIL_PATH_MARKERS))
    )

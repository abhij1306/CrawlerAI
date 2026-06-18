from app.services.extraction_v2.entities.contracts import EntitySet


def primary_product_id(entities: EntitySet) -> str | None:
    return entities.products[0].entity_id if len(entities.products) == 1 else None

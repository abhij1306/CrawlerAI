# Evidence coverage and JEV decision

Date: 2026-09-24. Each result number below has `page.html`, `record.json`, and
`diagnose.json` under `backend/artifacts/runs/1/results/<number>/`. The paired
diagnosis `fields` list is the frozen requested-field contract: `not_requested`
means the field was outside that URL's contract. Statuses below describe the
original capture, before the generic corrections in this plan.

| Result | Contract/status for cited issue | First owner or source classification |
| --- | --- | --- |
| 1 Sneaker Politics | brand `captured_published` | Attribute admission: unresolved template `{{ shop.name }}`. |
| 2 Sneakersnstuff | materials `captured_published` | Material collector/ranking; captured product-detail evidence is available. |
| 8 StockX | price, currency `not_present_in_captured_sources` | Acquisition/source absence; keep commercial fields missing. |
| 10 Target | color, size `not_requested` | Request selection intent only; query value is an opaque variant identity. |
| 14 Birkenstock | description `captured_published` | DOM scope admitted consent copy although product prose is captured. |
| 23 Puma Argentina | price, currency `captured_published` | DOM offer currency chose USD from ambiguous `$`; country locale supports ARS. |
| 33 Apple | description, price `captured_published` | DOM saved-device UI copy won; structured descriptions are promotional and rejected. |
| 36 Selfridges/CREED | brand `captured_published` | Derived page identity beat a manufacturer hint from title, URL, and product evidence. |
| 38 Peloton | description `captured_published`; price `not_present_in_captured_sources` | JS-state image description won; commercial price is uncaptured. |
| 54 Williams Sonoma/Breville | brand `captured_published` | Derived seller identity beat corroborated product brand. |
| 55 Amsterdam Vintage Watches/Rolex | brand `captured_published` | Derived seller identity beat corroborated product brand. |
| 61 Uniqlo | size `captured_published`; price `not_present_in_captured_sources` | URL option code `004` was published without a mapped label; price is uncaptured. |
| 63 H&M | color `captured_published` | DOM color panel absorbed adjacent Previous/Next controls. |
| 64 Puma US | gender `captured_published` | Invalid JS-state audience `Gender` passed admission. |
| 72 Ralph Lauren | color `not_requested` | Query states color intent, but missing public color is not a contract defect. |
| 77 Balmain | SKU, variants `captured_published` | Fragment identity `189322` should bind only to the existing 50 ml child, SKU `B02I01`. |

The result directory contains 81 URL occurrences and 80 product-resource URLs
after query and fragment removal. Results 24 and 60 are the same Zara product
resource with different request state. Their separate result artifacts exist;
the 80/81 difference is identity deduplication, not a lost input outcome.

## JEV go/no-go

**No-go.** None of these cited defects is a proven tie among two or more valid,
target-owned, field-compatible candidates. They are invalid values, wrong source
scope or ownership, request-binding defects, or facts absent from the capture.
The deterministic regression cases exercise those boundaries. The two earlier
hand-picked JEV probes are not held-out evidence. There is no qualifying labeled
candidate set on two unrelated sites, so the required incremental recovery
threshold cannot be met. No JEV version was called here; token use, cost,
latency, false publication, and abstention rates are therefore unmeasured.
Production promotion requires at least two additional correct grounded
recoveries on unrelated sites, zero unsupported publications, and measured
cost and latency within the configured limits. No connector or runtime path
was added.

# Policy Rule Reference

Policy rule schema version 1 is closed. Unknown fields and rule types are
rejected. JSON numbers for financial thresholds are rejected; use decimal
strings.

## Common Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `key` | yes | Unique stable key within one PolicyVersion |
| `type` | yes | One of the six rule types below |
| `severity` | no | `hard` or `soft`; default `soft` |
| `description` | no | Human-readable rationale |
| `subject` | by type | Asset type or ISO-style currency code |
| `target` | by type | Informational target weight |
| `lower` | by type | Inclusive lower bound |
| `upper` | by type | Inclusive upper bound |

## Rule Shapes

```json
[
  {
    "key": "equity-band",
    "type": "allocation_band",
    "severity": "soft",
    "subject": "stock",
    "target": "0.6",
    "lower": "0.5",
    "upper": "0.7"
  },
  {
    "key": "single-name",
    "type": "max_single_instrument_weight",
    "severity": "hard",
    "upper": "0.1"
  },
  {
    "key": "asset-cap",
    "type": "max_asset_type_weight",
    "subject": "stock",
    "upper": "0.8"
  },
  {
    "key": "cash-weight",
    "type": "min_cash_weight",
    "lower": "0.05"
  },
  {
    "key": "cash-reserve",
    "type": "min_cash_amount",
    "severity": "hard",
    "lower": "10000"
  },
  {
    "key": "currency-cap",
    "type": "max_currency_weight",
    "subject": "USD",
    "upper": "0.7"
  }
]
```

`min_cash_amount` is measured in Portfolio base currency. Currency exposure
uses base-currency-valued exposure divided by complete total value. Missing
asset or currency subjects evaluate as zero only for a complete valuation.

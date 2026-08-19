# Planning Contract

Planning input is a JSON array of scenarios. Financial values are decimal
strings. The same scenarios can be passed to `planning.compare` for an
ephemeral comparison or `planning.create` to persist an immutable Plan.

```json
[
  {
    "key": "target-contribution",
    "description": "Add new capital and keep the cash floor",
    "cash_available": "2000",
    "actions": [
      {
        "instrument_id": "<internal UUID>",
        "base_value_delta": "1500",
        "fee": "2.50",
        "tax_estimate": "0"
      }
    ]
  },
  {
    "key": "hold",
    "cash_available": "0",
    "actions": []
  }
]
```

`base_value_delta` is positive for a buy/contribution and negative for a sell.
All actions are hypothetical. `cash_available` is funded in the Portfolio base
currency before actions. Fees and tax estimates are explicit costs and are not
written to the Ledger.

Scenario status is one of `feasible`, `violates_policy`, `unavailable`, or
`rejected`. A feasible scenario has no Policy violations. Unresolved
constraints include a non-negative `gap` where a bound can be measured and an
explanation. `cash_reserve` and `allocation_gaps` make reserve and target
contribution tradeoffs explicit.

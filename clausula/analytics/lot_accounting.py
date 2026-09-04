from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from clausula.domain import canonical_decimal, dec


class LotAccountingError(ValueError):
    pass


LOT_METHODS = {"fifo", "lifo", "hifo"}


@dataclass
class _OpenLot:
    lot_id: str
    instrument_id: str
    source_transaction_id: str
    acquired_at: str
    side: str
    quantity: Decimal
    open_value: Decimal | None
    currency: str
    sequence: int

    @property
    def unit_open_value(self) -> Decimal:
        if self.open_value is None or self.quantity == 0:
            return Decimal("-Infinity")
        return self.open_value / self.quantity


def _allocate(total: Decimal, quantities: Sequence[Decimal]) -> list[Decimal]:
    quantity_total = sum(quantities, Decimal(0))
    if quantity_total <= 0:
        raise LotAccountingError("allocation quantity must be positive")
    remaining = total
    result: list[Decimal] = []
    for index, quantity in enumerate(quantities):
        value = remaining if index == len(quantities) - 1 else total * quantity / quantity_total
        result.append(value)
        remaining -= value
    return result


def _ordered_candidates(
    lots: list[_OpenLot], instrument_id: str, side: str, method: str
) -> list[_OpenLot]:
    candidates = [
        lot
        for lot in lots
        if lot.instrument_id == instrument_id and lot.side == side and lot.quantity > 0
    ]
    if method == "fifo":
        return sorted(candidates, key=lambda lot: lot.sequence)
    if method == "lifo":
        return sorted(candidates, key=lambda lot: lot.sequence, reverse=True)
    if method == "hifo":
        return sorted(
            candidates,
            key=lambda lot: (lot.unit_open_value, -lot.sequence),
            reverse=True,
        )
    raise LotAccountingError(f"unsupported lot method: {method}")


def _consume(
    lots: list[_OpenLot],
    instrument_id: str,
    side: str,
    quantity: Decimal,
    method: str,
) -> tuple[list[dict[str, Any]], Decimal]:
    remaining = quantity
    matches: list[dict[str, Any]] = []
    for lot in _ordered_candidates(lots, instrument_id, side, method):
        if remaining <= 0:
            break
        consumed = min(lot.quantity, remaining)
        if lot.open_value is None:
            allocated = None
        elif consumed == lot.quantity:
            allocated = lot.open_value
        else:
            allocated = lot.open_value * consumed / lot.quantity
        lot.quantity -= consumed
        if lot.open_value is not None and allocated is not None:
            lot.open_value -= allocated
        matches.append(
            {
                "lot_id": lot.lot_id,
                "source_transaction_id": lot.source_transaction_id,
                "acquired_at": lot.acquired_at,
                "side": side,
                "quantity": consumed,
                "open_value": allocated,
                "currency": lot.currency,
            }
        )
        remaining -= consumed
    return matches, remaining


def _consume_transfer_allocations(
    lots: list[_OpenLot],
    instrument_id: str,
    allocations: Sequence[Mapping[str, Any]],
) -> None:
    for allocation in allocations:
        source_id = str(allocation["source_transaction_id"])
        wanted = dec(allocation["quantity"])
        expected_basis = dec(allocation["basis"])
        remaining = wanted
        consumed_basis = Decimal(0)
        for lot in sorted(lots, key=lambda item: item.sequence):
            if (
                lot.instrument_id != instrument_id
                or lot.side != "long"
                or lot.source_transaction_id != source_id
                or lot.quantity <= 0
                or remaining <= 0
            ):
                continue
            consumed = min(lot.quantity, remaining)
            if lot.open_value is None:
                raise LotAccountingError("cannot transfer a long lot whose basis is unknown")
            allocated = (
                lot.open_value
                if consumed == lot.quantity
                else lot.open_value * consumed / lot.quantity
            )
            lot.quantity -= consumed
            lot.open_value -= allocated
            consumed_basis += allocated
            remaining -= consumed
        if remaining != 0:
            raise LotAccountingError(
                "security transfer allocation does not match available source lots"
            )
        if consumed_basis != expected_basis:
            raise LotAccountingError(
                "security transfer carried basis does not match selected source lots"
            )


def _apply_generalized_corporate_action(
    lots: list[_OpenLot],
    realized: list[dict[str, Any]],
    sequence: int,
    transaction_id: str,
    generalized: Mapping[str, Any],
) -> int:
    allocations = list(generalized.get("basis_allocations") or ())
    considerations = list(generalized.get("considerations") or ())
    cash_by_currency: dict[str, Decimal] = {}
    for item in considerations:
        if str(item["kind"]) == "cash":
            cash_by_currency[str(item["currency"])] = cash_by_currency.get(
                str(item["currency"]), Decimal(0)
            ) + dec(item["amount"])
    if allocations:
        action_type = str(generalized.get("action_type") or "")
        for allocation in allocations:
            source_id = str(allocation["source_instrument_id"])
            destination_id = allocation.get("destination_instrument_id")
            source_quantity = dec(allocation["source_quantity"])
            destination_quantity = dec(allocation["destination_quantity"])
            source_basis = dec(allocation["source_basis"])
            destination_basis = dec(allocation["destination_basis"])
            currency = str(allocation["currency"])
            if action_type == "spin_off":
                child_basis = destination_basis
                reduced = _reduce_spin_off_parent_basis(
                    lots, source_id, child_basis, currency
                )
                if reduced != child_basis:
                    raise LotAccountingError(
                        f"spin-off basis allocation mismatch for {source_id}: reduced {reduced}, expected {child_basis}"
                    )
                if destination_id is not None and destination_quantity > 0:
                    sequence += 1
                    lots.append(
                        _OpenLot(
                            f"{transaction_id}:ca:{sequence}",
                            str(destination_id),
                            transaction_id,
                            generalized.get("effective_at") or transaction_id,
                            "long",
                            destination_quantity,
                            destination_basis,
                            currency,
                            sequence,
                        )
                    )
                continue
            _consume_for_corporate_action(
                lots, source_id, source_quantity, source_basis
            )
            carried_to_cash = source_basis - destination_basis
            if carried_to_cash < 0:
                raise LotAccountingError(
                    f"corporate action basis allocation increases basis for {source_id}: "
                    f"destination {destination_basis} exceeds source {source_basis}"
                )
            cash_proceeds = cash_by_currency.get(currency, Decimal(0))
            if carried_to_cash > 0:
                realized.append(
                    _realized_row(
                        closing_transaction_id=transaction_id,
                        instrument_id=source_id,
                        direction="long",
                        quantity=source_quantity,
                        closing_value=cash_proceeds,
                        matches=[
                            {
                                "lot_id": "",
                                "source_transaction_id": transaction_id,
                                "acquired_at": generalized.get("effective_at") or transaction_id,
                                "side": "long",
                                "quantity": source_quantity,
                                "open_value": carried_to_cash,
                                "currency": currency,
                            }
                        ],
                        currency=currency,
                    )
                )
                cash_by_currency[currency] = Decimal(0)
            elif cash_proceeds > 0:
                raise LotAccountingError(
                    f"corporate action for {source_id} has cash consideration "
                    "but no basis allocated to cash"
                )
            if destination_id is not None and destination_quantity > 0:
                sequence += 1
                lots.append(
                    _OpenLot(
                        f"{transaction_id}:ca:{sequence}",
                        str(destination_id),
                        transaction_id,
                        generalized.get("effective_at") or transaction_id,
                        "long",
                        destination_quantity,
                        destination_basis,
                        currency,
                        sequence,
                    )
                )
    else:
        for currency, cash_amount in cash_by_currency.items():
            total_available = sum(
                (
                    lot.open_value or Decimal(0)
                    for lot in lots
                    if lot.side == "long" and lot.currency == currency and lot.quantity > 0
                ),
                Decimal(0),
            )
            if total_available == 0:
                continue
            consumed: list[_OpenLot] = []
            for lot in sorted(lots, key=lambda lot: lot.sequence):
                if lot.side != "long" or lot.currency != currency or lot.quantity <= 0:
                    continue
                consumed.append(lot)
            if not consumed:
                raise LotAccountingError(
                    "corporate action cash settlement requires long lots or explicit basis allocation"
                )
            realized.append(
                _realized_row(
                    closing_transaction_id=transaction_id,
                    instrument_id=str(consumed[0].instrument_id),
                    direction="long",
                    quantity=sum((lot.quantity for lot in consumed), Decimal(0)),
                    closing_value=cash_amount,
                    matches=[
                        {
                            "lot_id": lot.lot_id,
                            "source_transaction_id": lot.source_transaction_id,
                            "acquired_at": lot.acquired_at,
                            "side": "long",
                            "quantity": lot.quantity,
                            "open_value": lot.open_value,
                            "currency": lot.currency,
                        }
                        for lot in consumed
                    ],
                    currency=currency,
                )
            )
            for lot in consumed:
                lot.quantity = Decimal(0)
                lot.open_value = Decimal(0)
    return sequence


def _consume_for_corporate_action(
    lots: list[_OpenLot],
    instrument_id: str,
    quantity: Decimal,
    expected_basis: Decimal,
) -> Decimal:
    remaining = quantity
    consumed_basis = Decimal(0)
    for lot in sorted(lots, key=lambda lot: lot.sequence):
        if lot.instrument_id != instrument_id or lot.side != "long" or lot.quantity <= 0:
            continue
        if remaining <= 0:
            break
        consumed = min(lot.quantity, remaining)
        if lot.open_value is None:
            raise LotAccountingError(
                f"cannot transform a long lot whose basis is unknown: {lot.lot_id}"
            )
        allocated = (
            lot.open_value
            if consumed == lot.quantity
            else lot.open_value * consumed / lot.quantity
        )
        lot.quantity -= consumed
        lot.open_value -= allocated
        consumed_basis += allocated
        remaining -= consumed
    if remaining != 0:
        raise LotAccountingError(
            f"insufficient long lots for corporate action source {instrument_id}: remaining {remaining}"
        )
    if consumed_basis != expected_basis:
        raise LotAccountingError(
            f"corporate action basis mismatch for {instrument_id}: expected {expected_basis}, consumed {consumed_basis}"
        )
    return consumed_basis


def _reduce_spin_off_parent_basis(
    lots: list[_OpenLot],
    instrument_id: str,
    child_basis: Decimal,
    currency: str,
) -> Decimal:
    remaining = child_basis
    reduced = Decimal(0)
    for lot in sorted(lots, key=lambda lot: lot.sequence):
        if lot.instrument_id != instrument_id or lot.side != "long" or lot.quantity <= 0:
            continue
        if remaining <= 0:
            break
        if lot.open_value is None:
            raise LotAccountingError(
                f"cannot spin off from a long lot whose basis is unknown: {lot.lot_id}"
            )
        allocated = (
            lot.open_value
            if remaining >= lot.open_value
            else remaining
        )
        lot.open_value -= allocated
        reduced += allocated
        remaining -= allocated
    if remaining != 0:
        raise LotAccountingError(
            f"insufficient parent basis for spin-off of {instrument_id}: short {remaining}"
        )
    return reduced


def _realized_row(
    *,
    closing_transaction_id: str,
    instrument_id: str,
    direction: str,
    quantity: Decimal,
    closing_value: Decimal,
    matches: list[dict[str, Any]],
    currency: str,
) -> dict[str, Any]:
    open_values = [match["open_value"] for match in matches]
    total_open: Decimal | None = (
        None
        if any(value is None for value in open_values)
        else sum((value for value in open_values if value is not None), Decimal(0))
    )
    rendered = []
    closing_by_match = _allocate(closing_value, [match["quantity"] for match in matches])
    for match, allocated_close in zip(matches, closing_by_match, strict=True):
        opened = match["open_value"]
        gain = None
        if opened is not None:
            gain = allocated_close - opened if direction == "long" else opened - allocated_close
        rendered.append(
            {
                **match,
                "quantity": canonical_decimal(match["quantity"]),
                "open_value": None if opened is None else canonical_decimal(opened),
                "closing_value": canonical_decimal(allocated_close),
                "gain": None if gain is None else canonical_decimal(gain),
            }
        )
    gain = None
    if total_open is not None:
        gain = closing_value - total_open if direction == "long" else total_open - closing_value
    return {
        "closing_transaction_id": closing_transaction_id,
        "instrument_id": instrument_id,
        "direction": direction,
        "quantity": canonical_decimal(quantity),
        "open_value": None if total_open is None else canonical_decimal(total_open),
        "closing_value": canonical_decimal(closing_value),
        "gain": None if gain is None else canonical_decimal(gain),
        "currency": currency,
        "matches": rendered,
    }


def replay_lots(
    transactions: Sequence[Mapping[str, Any]],
    metadata_by_transaction: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    method: str = "fifo",
    allow_short: bool = False,
) -> dict[str, Any]:
    """Replay deterministic long/short lots under an explicit selection policy.

    `open_value` means cost basis for a long lot and net opening proceeds for a
    short lot. A buy first covers shorts; a sell first closes longs. Any residual
    trade crosses zero only when `allow_short=True`. Jurisdiction-specific tax
    law is deliberately outside this engine.
    """

    normalized_method = str(method).strip().lower()
    if normalized_method not in LOT_METHODS:
        raise LotAccountingError(
            f"lot method must be one of {', '.join(sorted(LOT_METHODS))}"
        )
    metadata_by_transaction = metadata_by_transaction or {}
    lots: list[_OpenLot] = []
    realized: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    sequence = 0

    for transaction in transactions:
        transaction_id = str(transaction["id"])
        transaction_type = str(transaction["type"]).lower()
        metadata = metadata_by_transaction.get(transaction_id, {})
        position_legs = [
            leg
            for leg in transaction.get("legs", ())
            if leg.get("leg_type") == "position" and leg.get("instrument_id")
        ]
        fees: dict[str, Decimal] = {}
        for leg in transaction.get("legs", ()):
            if leg.get("leg_type") == "fee":
                currency = str(leg["currency"])
                fees[currency] = fees.get(currency, Decimal(0)) + dec(leg["amount"])

        if transaction_type == "split":
            action = metadata.get("corporate_action")
            if not action:
                raise LotAccountingError(f"split transaction lacks metadata: {transaction_id}")
            ratio = dec(action["numerator"]) / dec(action["denominator"])
            instrument_id = str(action["instrument_id"])
            for lot in lots:
                if lot.instrument_id == instrument_id and lot.quantity > 0:
                    lot.quantity *= ratio
            continue

        transfer = metadata.get("security_transfer")
        if transaction_type == "transfer_in" and transfer:
            for allocation in transfer["allocations"]:
                sequence += 1
                lots.append(
                    _OpenLot(
                        f"{transaction_id}:{sequence}",
                        str(transfer["instrument_id"]),
                        str(allocation["source_transaction_id"]),
                        str(allocation["acquired_at"]),
                        "long",
                        dec(allocation["quantity"]),
                        dec(allocation["basis"]),
                        str(allocation["currency"]),
                        sequence,
                    )
                )
            continue
        if transaction_type == "transfer_out" and transfer:
            _consume_transfer_allocations(
                lots,
                str(transfer["instrument_id"]),
                transfer["allocations"],
            )
            continue

        generalized = metadata.get("generalized_corporate_action")
        if generalized:
            _apply_generalized_corporate_action(
                lots,
                realized,
                sequence,
                transaction_id,
                generalized,
            )
            continue

        for leg_index, leg in enumerate(position_legs, 1):
            instrument_id = str(leg["instrument_id"])
            quantity = dec(leg["quantity"])
            amount = dec(leg["amount"])
            currency = str(leg["currency"])
            fee = fees.get(currency, Decimal(0))

            if transaction_type == "buy" and quantity > 0:
                total_cost = amount + fee
                matches, uncovered = _consume(
                    lots, instrument_id, "short", quantity, normalized_method
                )
                covered = quantity - uncovered
                if covered > 0:
                    cover_cost = total_cost * covered / quantity
                    realized.append(
                        _realized_row(
                            closing_transaction_id=transaction_id,
                            instrument_id=instrument_id,
                            direction="short",
                            quantity=covered,
                            closing_value=cover_cost,
                            matches=matches,
                            currency=currency,
                        )
                    )
                if uncovered > 0:
                    long_cost = total_cost * uncovered / quantity
                    sequence += 1
                    lots.append(
                        _OpenLot(
                            f"{transaction_id}:{leg_index}",
                            instrument_id,
                            transaction_id,
                            str(transaction["effective_at"]),
                            "long",
                            uncovered,
                            long_cost,
                            currency,
                            sequence,
                        )
                    )
                continue

            if transaction_type == "sell" and quantity < 0:
                sold = -quantity
                net_proceeds = -amount - fee
                matches, remaining = _consume(
                    lots, instrument_id, "long", sold, normalized_method
                )
                closed = sold - remaining
                if closed > 0:
                    close_proceeds = net_proceeds * closed / sold
                    realized.append(
                        _realized_row(
                            closing_transaction_id=transaction_id,
                            instrument_id=instrument_id,
                            direction="long",
                            quantity=closed,
                            closing_value=close_proceeds,
                            matches=matches,
                            currency=currency,
                        )
                    )
                if remaining > 0:
                    if not allow_short:
                        available = sold - remaining
                        raise LotAccountingError(
                            f"insufficient long quantity for {instrument_id}: requested {sold}, available {available}"
                        )
                    short_proceeds = net_proceeds * remaining / sold
                    sequence += 1
                    lots.append(
                        _OpenLot(
                            f"{transaction_id}:{leg_index}:short",
                            instrument_id,
                            transaction_id,
                            str(transaction["effective_at"]),
                            "short",
                            remaining,
                            short_proceeds,
                            currency,
                            sequence,
                        )
                    )
                continue

            if quantity > 0:
                sequence += 1
                lots.append(
                    _OpenLot(
                        f"{transaction_id}:{leg_index}",
                        instrument_id,
                        transaction_id,
                        str(transaction["effective_at"]),
                        "long",
                        quantity,
                        None,
                        currency,
                        sequence,
                    )
                )
                warnings.append(
                    {
                        "kind": "unknown_basis",
                        "transaction_id": transaction_id,
                        "instrument_id": instrument_id,
                        "quantity": canonical_decimal(quantity),
                    }
                )
            elif quantity < 0:
                raise LotAccountingError(
                    f"unsupported negative position leg for transaction type {transaction_type}"
                )

    open_lots: list[dict[str, Any]] = []
    long_basis: dict[str, Decimal] = {}
    short_proceeds: dict[str, Decimal] = {}
    realized_gain: dict[str, Decimal] = {}
    for lot in sorted((lot for lot in lots if lot.quantity > 0), key=lambda item: item.sequence):
        unit_value = None if lot.open_value is None else lot.open_value / lot.quantity
        row = {
            "lot_id": lot.lot_id,
            "instrument_id": lot.instrument_id,
            "source_transaction_id": lot.source_transaction_id,
            "acquired_at": lot.acquired_at,
            "side": lot.side,
            "quantity": canonical_decimal(lot.quantity),
            "open_value": None if lot.open_value is None else canonical_decimal(lot.open_value),
            "unit_open_value": None if unit_value is None else canonical_decimal(unit_value),
            "currency": lot.currency,
        }
        if lot.side == "long":
            row["cost_basis"] = row["open_value"]
            row["unit_cost"] = row["unit_open_value"]
            if lot.open_value is not None:
                long_basis[lot.currency] = long_basis.get(lot.currency, Decimal(0)) + lot.open_value
        else:
            row["opening_proceeds"] = row["open_value"]
            row["unit_opening_proceeds"] = row["unit_open_value"]
            if lot.open_value is not None:
                short_proceeds[lot.currency] = short_proceeds.get(lot.currency, Decimal(0)) + lot.open_value
        open_lots.append(row)
    for row in realized:
        if row["gain"] is not None:
            currency = row["currency"]
            realized_gain[currency] = realized_gain.get(currency, Decimal(0)) + dec(row["gain"])

    return {
        "method": normalized_method.upper(),
        "allow_short": allow_short,
        "open_lots": open_lots,
        "realized": realized,
        "open_basis_by_currency": {
            key: canonical_decimal(value) for key, value in sorted(long_basis.items())
        },
        "open_short_proceeds_by_currency": {
            key: canonical_decimal(value) for key, value in sorted(short_proceeds.items())
        },
        "realized_gain_by_currency": {
            key: canonical_decimal(value) for key, value in sorted(realized_gain.items())
        },
        "warnings": warnings,
    }

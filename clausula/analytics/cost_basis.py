from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from clausula.domain import canonical_decimal, dec


class CostBasisError(ValueError):
    pass


@dataclass
class _Lot:
    lot_id: str
    instrument_id: str
    source_transaction_id: str
    acquired_at: str
    quantity: Decimal
    basis: Decimal | None
    currency: str


def _allocate(total: Decimal, quantities: Sequence[Decimal]) -> list[Decimal]:
    quantity_total = sum(quantities, Decimal(0))
    if quantity_total <= 0:
        raise CostBasisError("allocation quantity must be positive")
    remaining = total
    result: list[Decimal] = []
    for index, quantity in enumerate(quantities):
        allocated = remaining if index == len(quantities) - 1 else total * quantity / quantity_total
        result.append(allocated)
        remaining -= allocated
    return result


def _consume(
    lots: list[_Lot], instrument_id: str, quantity: Decimal
) -> list[dict[str, Any]]:
    remaining = quantity
    matches: list[dict[str, Any]] = []
    for lot in lots:
        if lot.instrument_id != instrument_id or lot.quantity <= 0 or remaining <= 0:
            continue
        consumed = min(lot.quantity, remaining)
        if lot.basis is None:
            allocated_basis = None
        elif consumed == lot.quantity:
            allocated_basis = lot.basis
        else:
            allocated_basis = lot.basis * consumed / lot.quantity
        lot.quantity -= consumed
        if lot.basis is not None and allocated_basis is not None:
            lot.basis -= allocated_basis
        matches.append(
            {
                "lot_id": lot.lot_id,
                "source_transaction_id": lot.source_transaction_id,
                "acquired_at": lot.acquired_at,
                "quantity": consumed,
                "basis": allocated_basis,
                "currency": lot.currency,
            }
        )
        remaining -= consumed
    if remaining != 0:
        available = quantity - remaining
        raise CostBasisError(
            f"insufficient quantity for {instrument_id}: requested {quantity}, available {available}"
        )
    return matches


def replay_fifo(
    transactions: Sequence[Mapping[str, Any]],
    metadata_by_transaction: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata_by_transaction = metadata_by_transaction or {}
    lots: list[_Lot] = []
    realized: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for transaction in transactions:
        transaction_id = transaction["id"]
        transaction_type = transaction["type"]
        metadata = metadata_by_transaction.get(transaction_id, {})
        position_legs = [
            leg
            for leg in transaction.get("legs", ())
            if leg.get("leg_type") == "position" and leg.get("instrument_id")
        ]
        fees: dict[str, Decimal] = {}
        for leg in transaction.get("legs", ()):
            if leg.get("leg_type") == "fee":
                currency = leg["currency"]
                fees[currency] = fees.get(currency, Decimal(0)) + dec(leg["amount"])

        if transaction_type == "split":
            action = metadata.get("corporate_action")
            if not action:
                raise CostBasisError(f"split transaction lacks metadata: {transaction_id}")
            ratio = dec(action["numerator"]) / dec(action["denominator"])
            instrument_id = action["instrument_id"]
            for lot in lots:
                if lot.instrument_id == instrument_id and lot.quantity > 0:
                    lot.quantity *= ratio
            continue

        transfer = metadata.get("security_transfer")
        if transaction_type == "transfer_in" and transfer:
            for index, allocation in enumerate(transfer["allocations"], 1):
                lots.append(
                    _Lot(
                        f"{transaction_id}:{index}",
                        transfer["instrument_id"],
                        allocation["source_transaction_id"],
                        allocation["acquired_at"],
                        dec(allocation["quantity"]),
                        dec(allocation["basis"]),
                        allocation["currency"],
                    )
                )
            continue
        if transaction_type == "transfer_out" and transfer:
            matches = _consume(
                lots,
                transfer["instrument_id"],
                dec(transfer["quantity"]),
            )
            actual_basis = sum(
                (match["basis"] for match in matches if match["basis"] is not None),
                Decimal(0),
            )
            if any(match["basis"] is None for match in matches):
                raise CostBasisError("cannot transfer lots whose basis is unknown")
            if actual_basis != dec(transfer["carried_basis"]):
                raise CostBasisError("security transfer carried basis does not match FIFO lots")
            continue

        for leg_index, leg in enumerate(position_legs, 1):
            instrument_id = leg["instrument_id"]
            quantity = dec(leg["quantity"])
            amount = dec(leg["amount"])
            currency = leg["currency"]
            if quantity > 0:
                if transaction_type == "buy":
                    basis = amount + fees.get(currency, Decimal(0))
                else:
                    basis = None
                    warnings.append(
                        {
                            "kind": "unknown_basis",
                            "transaction_id": transaction_id,
                            "instrument_id": instrument_id,
                            "quantity": canonical_decimal(quantity),
                        }
                    )
                lots.append(
                    _Lot(
                        f"{transaction_id}:{leg_index}",
                        instrument_id,
                        transaction_id,
                        transaction["effective_at"],
                        quantity,
                        basis,
                        currency,
                    )
                )
            elif quantity < 0:
                sold_quantity = -quantity
                matches = _consume(lots, instrument_id, sold_quantity)
                if transaction_type == "sell":
                    proceeds = -amount - fees.get(currency, Decimal(0))
                    proceeds_by_match = _allocate(
                        proceeds, [match["quantity"] for match in matches]
                    )
                    rendered_matches = []
                    total_basis: Decimal | None = Decimal(0)
                    for match, allocated_proceeds in zip(matches, proceeds_by_match, strict=True):
                        basis = match["basis"]
                        if basis is None:
                            total_basis = None
                        elif total_basis is not None:
                            total_basis += basis
                        rendered_matches.append(
                            {
                                **match,
                                "quantity": canonical_decimal(match["quantity"]),
                                "basis": None if basis is None else canonical_decimal(basis),
                                "proceeds": canonical_decimal(allocated_proceeds),
                                "gain": None
                                if basis is None
                                else canonical_decimal(allocated_proceeds - basis),
                            }
                        )
                    realized.append(
                        {
                            "sale_transaction_id": transaction_id,
                            "instrument_id": instrument_id,
                            "quantity": canonical_decimal(sold_quantity),
                            "proceeds": canonical_decimal(proceeds),
                            "cost_basis": None
                            if total_basis is None
                            else canonical_decimal(total_basis),
                            "gain": None
                            if total_basis is None
                            else canonical_decimal(proceeds - total_basis),
                            "currency": currency,
                            "matches": rendered_matches,
                        }
                    )
                elif transaction_type == "transfer_out":
                    warnings.append(
                        {
                            "kind": "unlinked_security_transfer",
                            "transaction_id": transaction_id,
                            "instrument_id": instrument_id,
                        }
                    )

    open_lots = []
    for lot in lots:
        if lot.quantity <= 0:
            continue
        open_lots.append(
            {
                "lot_id": lot.lot_id,
                "instrument_id": lot.instrument_id,
                "source_transaction_id": lot.source_transaction_id,
                "acquired_at": lot.acquired_at,
                "quantity": canonical_decimal(lot.quantity),
                "cost_basis": None if lot.basis is None else canonical_decimal(lot.basis),
                "unit_cost": None
                if lot.basis is None
                else canonical_decimal(lot.basis / lot.quantity),
                "currency": lot.currency,
            }
        )
    realized_by_currency: dict[str, Decimal] = {}
    basis_by_currency: dict[str, Decimal] = {}
    for item in realized:
        if item["gain"] is not None:
            realized_by_currency[item["currency"]] = realized_by_currency.get(
                item["currency"], Decimal(0)
            ) + dec(item["gain"])
    for lot in open_lots:
        if lot["cost_basis"] is not None:
            basis_by_currency[lot["currency"]] = basis_by_currency.get(
                lot["currency"], Decimal(0)
            ) + dec(lot["cost_basis"])
    return {
        "method": "FIFO",
        "open_lots": open_lots,
        "realized": realized,
        "open_basis_by_currency": {
            key: canonical_decimal(value) for key, value in sorted(basis_by_currency.items())
        },
        "realized_gain_by_currency": {
            key: canonical_decimal(value)
            for key, value in sorted(realized_by_currency.items())
        },
        "warnings": warnings,
    }


def plan_fifo_transfer(
    report: Mapping[str, Any], instrument_id: str, quantity: Decimal | str | int
) -> list[dict[str, str]]:
    remaining = dec(quantity)
    if remaining <= 0:
        raise CostBasisError("transfer quantity must be positive")
    allocations: list[dict[str, str]] = []
    for lot in report["open_lots"]:
        if lot["instrument_id"] != instrument_id or remaining <= 0:
            continue
        if lot["cost_basis"] is None:
            raise CostBasisError("cannot transfer lots whose basis is unknown")
        available = dec(lot["quantity"])
        consumed = min(available, remaining)
        basis = (
            dec(lot["cost_basis"])
            if consumed == available
            else dec(lot["cost_basis"]) * consumed / available
        )
        allocations.append(
            {
                "source_transaction_id": lot["source_transaction_id"],
                "acquired_at": lot["acquired_at"],
                "quantity": canonical_decimal(consumed),
                "basis": canonical_decimal(basis),
                "currency": lot["currency"],
            }
        )
        remaining -= consumed
    if remaining != 0:
        raise CostBasisError("insufficient known-basis quantity for transfer")
    return allocations

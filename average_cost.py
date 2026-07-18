from __future__ import annotations

import math
from typing import Optional


def _non_negative_number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}은 숫자여야 합니다.") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label}은 0 이상의 유한한 숫자여야 합니다.")
    return number


def calculate_average_cost(
    holding_quantity: object,
    current_average_price: object,
    purchase_price: object,
    *,
    purchase_quantity: Optional[object] = None,
    purchase_amount: Optional[object] = None,
) -> dict:
    holding_quantity = _non_negative_number(holding_quantity, "보유 수량")
    current_average_price = _non_negative_number(current_average_price, "현재 평균단가")
    purchase_price = _non_negative_number(purchase_price, "추가 매수가")

    if (purchase_quantity is None) == (purchase_amount is None):
        raise ValueError("추가 수량과 추가 금액 중 하나만 입력해야 합니다.")
    if purchase_amount is not None:
        purchase_amount = _non_negative_number(purchase_amount, "추가 매수금액")
        additional_quantity = purchase_amount / purchase_price if purchase_price > 0 else 0.0
        additional_cost = purchase_amount
    else:
        additional_quantity = _non_negative_number(purchase_quantity, "추가 수량")
        additional_cost = additional_quantity * purchase_price

    existing_cost = holding_quantity * current_average_price
    total_quantity = holding_quantity + additional_quantity
    total_cost = existing_cost + additional_cost
    new_average_price = total_cost / total_quantity if total_quantity > 0 else 0.0
    average_change_pct = (
        (new_average_price / current_average_price - 1) * 100
        if current_average_price > 0 and total_quantity > 0
        else 0.0
    )
    return {
        "existing_cost": existing_cost,
        "additional_quantity": additional_quantity,
        "additional_cost": additional_cost,
        "total_quantity": total_quantity,
        "total_cost": total_cost,
        "new_average_price": new_average_price,
        "average_change_pct": average_change_pct,
    }

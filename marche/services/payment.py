"""Stripe への接続。ビューは app.extensions["payment"] 経由で利用する。"""

import time

import stripe
from flask import current_app, url_for

CHECKOUT_EXPIRES_MINUTES = 31


class PaymentError(Exception):
    """画面に表示できる決済エラー。"""


def _client() -> stripe.StripeClient:
    key = current_app.config["STRIPE_SECRET_KEY"]
    if not key:
        raise PaymentError("決済の設定がされていません")
    return stripe.StripeClient(key)


def create_checkout_session(order) -> tuple[str, str]:
    complete_url = url_for("orders.complete", order_id=order.id, _external=True)
    params = {
        "mode": "payment",
        "line_items": [
            {
                "quantity": item.quantity,
                "price_data": {
                    "currency": "jpy",
                    # 円は100倍せず、保存した注文明細の単価をそのまま渡す
                    "unit_amount": item.unit_price,
                    "product_data": {"name": item.product_name},
                },
            }
            for item in order.items
        ],
        "customer_email": order.user.email,
        "metadata": {"order_id": str(order.id)},
        "success_url": complete_url + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": url_for("orders.cancel", order_id=order.id, _external=True),
        "expires_at": int(time.time()) + CHECKOUT_EXPIRES_MINUTES * 60,
    }
    try:
        session = _client().v1.checkout.sessions.create(params)
    except stripe.StripeError as e:
        # 例外本文にはキーや個人情報が含まれる可能性があるため記録しない
        current_app.logger.warning(
            "Checkout Session の作成に失敗 order_id=%s", order.id
        )
        raise PaymentError(
            "決済ページを開けませんでした。時間をおいてもう一度お試しください"
        ) from e
    return session.id, session.url


def retrieve_session(session_id: str):
    try:
        return _client().v1.checkout.sessions.retrieve(session_id)
    except stripe.StripeError as e:
        raise PaymentError("支払いの状態を確かめられませんでした") from e


def expire_session(session_id: str) -> None:
    try:
        _client().v1.checkout.sessions.expire(session_id)
    except stripe.StripeError as e:
        raise PaymentError("この注文は取り消せませんでした") from e

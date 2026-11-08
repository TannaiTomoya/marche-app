"""Stripe を呼ぶのはこのファイルだけ。ビューは current_app.extensions["payment"] 経由で呼ぶ"""

import logging
import time

import stripe
from flask import current_app, url_for

logger = logging.getLogger(__name__)

# Checkout Session の有効期限。Stripe の最短は30分なので、時計のずれを見込んで31分
SESSION_MINUTES = 31


class PaymentError(Exception):
    """画面に出せる日本語のメッセージを持つ"""


def make_client() -> stripe.StripeClient:
    key = current_app.config.get("STRIPE_SECRET_KEY")
    if not key:
        raise PaymentError("決済の設定がされていません")
    return stripe.StripeClient(key)


def build_session_params(order) -> dict:
    """注文明細（DB）から Checkout Session の内容を作る。金額はフォームから受け取らない"""
    complete_url = url_for("orders.complete", order_id=order.id, _external=True)
    return {
        "mode": "payment",
        "line_items": [
            {
                "price_data": {
                    "currency": "jpy",
                    # 日本円は小数の無い通貨なので、円のまま渡す（100倍しない）
                    "unit_amount": item.unit_price,
                    "product_data": {"name": item.product_name},
                },
                "quantity": item.quantity,
            }
            for item in order.items
        ],
        "metadata": {"order_id": str(order.id)},
        "expires_at": int(time.time()) + SESSION_MINUTES * 60,
        # {CHECKOUT_SESSION_ID} は Stripe が置き換える。url_for に渡すと {} がエスケープされるので後ろに足す
        "success_url": complete_url + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": url_for("orders.cancel", order_id=order.id, _external=True),
    }


def create_checkout_session(order) -> tuple[str, str]:
    """決済ページを作り、(Session の ID, 決済ページの URL) を返す"""
    try:
        session = make_client().v1.checkout.sessions.create(build_session_params(order))
    except stripe.StripeError as e:
        logger.error("Checkout Session を作れませんでした order_id=%s: %s", order.id, e)
        raise PaymentError(
            "決済ページを開けませんでした。時間をおいてもう一度お試しください"
        ) from e
    return session.id, session.url


def retrieve_session(session_id: str):
    """支払いの状態を Stripe に問い合わせる（完了ページで使う）"""
    try:
        return make_client().v1.checkout.sessions.retrieve(session_id)
    except stripe.StripeError as e:
        logger.error("Checkout Session を取得できませんでした: %s", e)
        raise PaymentError("支払いの状態を確かめられませんでした") from e


def expire_session(session_id: str) -> None:
    """決済ページを期限切れにする（中断ページで使う）。支払い済みなら失敗する"""
    try:
        make_client().v1.checkout.sessions.expire(session_id)
    except stripe.StripeError as e:
        logger.warning("Checkout Session を期限切れにできませんでした: %s", e)
        raise PaymentError("この注文は取り消せませんでした") from e


def construct_webhook_event(payload: bytes, signature: str, secret: str) -> dict:
    """Webhook の署名を確かめて、イベントを dict で返す。不正なら ValueError"""
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except stripe.SignatureVerificationError as e:
        raise ValueError("署名が正しくありません") from e
    return event.to_dict()

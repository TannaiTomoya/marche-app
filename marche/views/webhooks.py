import logging

from flask import Blueprint, current_app, request

from marche.extensions import csrf, db
from marche.models import Order
from marche.services.inventory import mark_as_paid
from marche.services.payment import construct_webhook_event

logger = logging.getLogger(__name__)

bp = Blueprint("webhooks", __name__)


@bp.route("/stripe/webhook", methods=["POST"])
@csrf.exempt  # Stripe からの POST には CSRF トークンが無い。代わりに署名で確かめる
def stripe_webhook():
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET が設定されていません")
        return "", 400
    try:
        event = construct_webhook_event(
            request.get_data(), request.headers.get("Stripe-Signature", ""), secret
        )
    except ValueError:
        return "", 400

    # 扱わないイベントにも 200 を返す（エラーを返すと Stripe が送り直し続ける）
    if event.get("type") != "checkout.session.completed":
        return "", 200
    session = event["data"]["object"]
    if session.get("payment_status") != "paid":
        return "", 200

    order_id = (session.get("metadata") or {}).get("order_id", "")
    order = db.session.get(Order, int(order_id)) if str(order_id).isdigit() else None
    if order is None or order.stripe_checkout_session_id != session.get("id"):
        logger.warning("Webhook の注文が見つからないか、Session が一致しません")
        return "", 200

    mark_as_paid(order, session.get("payment_intent"))
    return "", 200

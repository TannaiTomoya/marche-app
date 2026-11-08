"""#2 Stripe Webhook、#4 注文確認メール。署名はフェイクにせず、本物の検証を通す"""

import json

import stripe

from marche.extensions import db
from marche.models import OrderStatus
from marche.services import mail
from marche.services.inventory import cancel_order, create_order
from tests.conftest import WEBHOOK_SECRET


def make_paid_order(customer, product, quantity=2):
    order = create_order(customer, {product.id: quantity})
    order.stripe_checkout_session_id = f"cs_test_{order.id}"
    db.session.commit()
    return order


def event_payload(
    order, payment_status="paid", event_type="checkout.session.completed"
):
    return json.dumps(
        {
            "id": "evt_test",
            "object": "event",
            "type": event_type,
            "data": {
                "object": {
                    "id": order.stripe_checkout_session_id,
                    "object": "checkout.session",
                    "payment_status": payment_status,
                    "payment_intent": "pi_test_1",
                    "metadata": {"order_id": str(order.id)},
                }
            },
        }
    )


def post_webhook(client, payload, secret=WEBHOOK_SECRET, signature=None):
    if signature is None:
        signature = stripe.WebhookSignature.generate_signature_header(payload, secret)
    return client.post(
        "/stripe/webhook",
        data=payload,
        headers={"Stripe-Signature": signature},
        content_type="application/json",
    )


def outbox(app):
    return app.extensions["mail_outbox"]


# --- 正常（T16） ---


def test_正しい署名で支払い済みになり在庫が減りメールが1通(
    app, client, producer, customer, make_product
):
    product = make_product(producer, name="トマト", stock=5, price=300)
    order = make_paid_order(customer, product, 2)
    response = post_webhook(client, event_payload(order))
    assert response.status_code == 200
    assert order.status == OrderStatus.PAID
    assert order.paid_at is not None
    assert order.stripe_payment_intent_id == "pi_test_1"
    db.session.refresh(product)
    assert product.stock == 3
    assert len(outbox(app)) == 1
    message = outbox(app)[0]
    assert message["To"] == customer.email
    assert f"注文番号 {order.id}" in message["Subject"]
    body = message.get_content()
    assert "トマト" in body and "600円" in body


# --- 署名（T17） ---


def test_署名が違うと400で注文は変わらない(client, producer, customer, make_product):
    product = make_product(producer, stock=5)
    order = make_paid_order(customer, product)
    response = post_webhook(client, event_payload(order), secret="whsec_wrong")
    assert response.status_code == 400
    assert order.status == OrderStatus.PENDING


def test_署名が無いと400(client, producer, customer, make_product):
    product = make_product(producer)
    order = make_paid_order(customer, product)
    response = post_webhook(client, event_payload(order), signature="")
    assert response.status_code == 400
    assert order.status == OrderStatus.PENDING


# --- 二重（T18） ---


def test_同じWebhookが2回来ても在庫は1回だけ減りメールも1通(
    app, client, producer, customer, make_product
):
    product = make_product(producer, stock=5)
    order = make_paid_order(customer, product, 2)
    payload = event_payload(order)
    assert post_webhook(client, payload).status_code == 200
    assert post_webhook(client, payload).status_code == 200
    db.session.refresh(product)
    assert product.stock == 3
    assert len(outbox(app)) == 1


# --- 未払い・取り消し済み・関係ないイベント（T19） ---


def test_unpaidなら確定しない(app, client, producer, customer, make_product):
    product = make_product(producer, stock=5)
    order = make_paid_order(customer, product)
    post_webhook(client, event_payload(order, payment_status="unpaid"))
    assert order.status == OrderStatus.PENDING
    assert outbox(app) == []


def test_取り消し済みの注文は支払い済みにならない(
    client, producer, customer, make_product
):
    product = make_product(producer, stock=5)
    order = make_paid_order(customer, product)
    cancel_order(order)
    post_webhook(client, event_payload(order))
    assert order.status == OrderStatus.CANCELLED
    db.session.refresh(product)
    assert product.stock == 5


def test_Sessionが一致しなければ確定しない(client, producer, customer, make_product):
    product = make_product(producer)
    order = make_paid_order(customer, product)
    payload = event_payload(order).replace(order.stripe_checkout_session_id, "cs_other")
    assert post_webhook(client, payload).status_code == 200
    assert order.status == OrderStatus.PENDING


def test_扱わないイベントは200で何もしない(client, producer, customer, make_product):
    product = make_product(producer)
    order = make_paid_order(customer, product)
    payload = event_payload(order, event_type="payment_intent.created")
    assert post_webhook(client, payload).status_code == 200
    assert order.status == OrderStatus.PENDING


def test_在庫が足りなくても0未満にはならない(client, producer, customer, make_product):
    product = make_product(producer, stock=5)
    order = make_paid_order(customer, product, 3)
    product.stock = 1  # 支払い中に生産者が在庫を減らした
    db.session.commit()
    post_webhook(client, event_payload(order))
    db.session.refresh(product)
    assert product.stock == 0
    assert order.status == OrderStatus.PAID


# --- CSRF（T22） ---


def test_WebhookはCSRFの対象外で署名で弾かれる(app, producer, customer, make_product):
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    product = make_product(producer)
    order = make_paid_order(customer, product)
    assert post_webhook(client, event_payload(order)).status_code == 200
    assert order.status == OrderStatus.PAID
    response = post_webhook(client, event_payload(order), secret="whsec_wrong")
    assert response.status_code == 400


# --- #4 メールの失敗 ---


def test_メールが送れなくても支払いの確定は取り消さない(
    client, producer, customer, make_product, monkeypatch
):
    def broken(order):
        raise OSError("SMTP に接続できない")

    monkeypatch.setattr(mail, "send_order_paid", broken)
    product = make_product(producer, stock=5)
    order = make_paid_order(customer, product)
    assert post_webhook(client, event_payload(order)).status_code == 200
    assert order.status == OrderStatus.PAID

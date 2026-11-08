"""#1 Stripe Checkout、#3 支払い完了・中断ページ"""

from types import SimpleNamespace

import pytest
import stripe

from marche.extensions import db
from marche.models import Order, OrderStatus
from marche.services import payment
from marche.services.inventory import available_stock, create_order
from marche.services.payment import PaymentError


def order_with_session(customer, product, quantity=1):
    order = create_order(customer, {product.id: quantity})
    order.stripe_checkout_session_id = f"cs_test_{order.id}"
    db.session.commit()
    return order


# --- #1 Stripe へ移動（T13・T14） ---


def test_Stripeの失敗なら注文を取り消してカートは残す(
    client, producer, customer, login, make_product, fake_payment
):
    fake_payment.error = PaymentError("決済ページを開けませんでした")
    product = make_product(producer)
    login(customer)
    client.post(f"/cart/add/{product.id}", data={"quantity": "1"})
    response = client.post("/orders/", follow_redirects=True)
    assert "決済ページを開けませんでした" in response.text
    order = db.session.scalar(db.select(Order))
    assert order.status == OrderStatus.CANCELLED
    with client.session_transaction() as session:
        assert session["cart"] == {str(product.id): 1}
    assert available_stock(product) == product.stock  # 押さえは戻る


# --- services/payment.py（T15）。Stripe のクライアントを差し替えて、渡す値を確かめる ---


class RecordingSessions:
    def __init__(self, error=None):
        self.params = None
        self.error = error

    def create(self, params):
        if self.error:
            raise self.error
        self.params = params
        return SimpleNamespace(id="cs_test_x", url="https://checkout.stripe.test/x")


def fake_client(sessions):
    return SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=sessions))
    )


def test_line_itemsに明細の単価とjpyとorder_idが入る(
    app, producer, customer, make_product, monkeypatch
):
    tomato = make_product(producer, name="トマト", price=300)
    order = create_order(customer, {tomato.id: 2})
    sessions = RecordingSessions()
    monkeypatch.setattr(payment, "make_client", lambda: fake_client(sessions))
    with app.test_request_context():
        assert payment.create_checkout_session(order) == (
            "cs_test_x",
            "https://checkout.stripe.test/x",
        )
    item = sessions.params["line_items"][0]
    assert item["price_data"]["unit_amount"] == 300  # 円のまま（100倍しない）
    assert item["price_data"]["currency"] == "jpy"
    assert item["price_data"]["product_data"]["name"] == "トマト"
    assert item["quantity"] == 2
    assert sessions.params["metadata"] == {"order_id": str(order.id)}
    assert sessions.params["success_url"].endswith(
        f"/orders/{order.id}/complete?session_id={{CHECKOUT_SESSION_ID}}"
    )


def test_StripeのエラーはPaymentErrorになる(
    app, producer, customer, make_product, monkeypatch
):
    product = make_product(producer)
    order = create_order(customer, {product.id: 1})
    sessions = RecordingSessions(error=stripe.APIConnectionError("network"))
    monkeypatch.setattr(payment, "make_client", lambda: fake_client(sessions))
    with app.test_request_context(), pytest.raises(PaymentError):
        payment.create_checkout_session(order)


def test_キーが無ければPaymentErrorになる(app):
    app.config["STRIPE_SECRET_KEY"] = ""
    with pytest.raises(PaymentError):
        payment.make_client()


# --- #3 支払い完了ページ（T20） ---


def test_完了ページでStripeがpaidなら確定する(
    client, producer, customer, login, make_product, fake_payment
):
    product = make_product(producer, stock=5)
    order = order_with_session(customer, product, 2)
    login(customer)
    response = client.get(
        f"/orders/{order.id}/complete?session_id={order.stripe_checkout_session_id}"
    )
    assert response.status_code == 200
    assert "ご注文ありがとうございます" in response.text
    assert order.status == OrderStatus.PAID
    db.session.refresh(product)
    assert product.stock == 3


def test_完了ページでまだ支払われていなければ確認中(
    client, producer, customer, login, make_product, fake_payment
):
    fake_payment.payment_status = "unpaid"
    product = make_product(producer)
    order = order_with_session(customer, product)
    login(customer)
    response = client.get(
        f"/orders/{order.id}/complete?session_id={order.stripe_checkout_session_id}"
    )
    assert "確認しています" in response.text
    assert 'http-equiv="refresh"' in response.text
    assert order.status == OrderStatus.PENDING


def test_完了ページのsession_idが違えば確定しない(
    client, producer, customer, login, make_product, fake_payment
):
    product = make_product(producer)
    order = order_with_session(customer, product)
    login(customer)
    client.get(f"/orders/{order.id}/complete?session_id=cs_test_other")
    assert order.status == OrderStatus.PENDING
    assert ("retrieve", "cs_test_other") not in fake_payment.calls


def test_他人の注文の完了ページは403(
    client, producer, customer, other_producer, login, make_product
):
    product = make_product(producer)
    order = order_with_session(customer, product)
    login(other_producer)
    response = client.get(
        f"/orders/{order.id}/complete?session_id={order.stripe_checkout_session_id}"
    )
    assert response.status_code == 403
    assert order.status == OrderStatus.PENDING


# --- #3 支払い中断ページ（T21） ---


def test_中断ページで取り消すと在庫の押さえが戻る(
    client, producer, customer, login, make_product, fake_payment
):
    product = make_product(producer, stock=5)
    order = order_with_session(customer, product, 3)
    assert available_stock(product) == 2
    login(customer)
    assert "この注文を取り消す" in client.get(f"/orders/{order.id}/cancel").text
    client.post(f"/orders/{order.id}/cancel")
    assert order.status == OrderStatus.CANCELLED
    assert ("expire", order.stripe_checkout_session_id) in fake_payment.calls
    assert available_stock(product) == 5


def test_期限切れにできなければ取り消さない(
    client, producer, customer, login, make_product, fake_payment
):
    fake_payment.expire_error = PaymentError("この注文は取り消せませんでした")
    product = make_product(producer)
    order = order_with_session(customer, product)
    login(customer)
    client.post(f"/orders/{order.id}/cancel")
    assert order.status == OrderStatus.PENDING


def test_支払い済みの注文は取り消せない(
    client, producer, customer, login, make_product, fake_payment
):
    product = make_product(producer)
    order = order_with_session(customer, product)
    order.status = OrderStatus.PAID
    db.session.commit()
    login(customer)
    client.post(f"/orders/{order.id}/cancel")
    assert order.status == OrderStatus.PAID
    assert not any(call[0] == "expire" for call in fake_payment.calls)


def test_他人の注文は取り消せない(
    client, producer, customer, other_producer, login, make_product
):
    product = make_product(producer)
    order = order_with_session(customer, product)
    login(other_producer)
    assert client.get(f"/orders/{order.id}/cancel").status_code == 403
    assert client.post(f"/orders/{order.id}/cancel").status_code == 403
    assert order.status == OrderStatus.PENDING

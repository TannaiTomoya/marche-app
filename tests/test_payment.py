import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import stripe

from marche.extensions import db
from marche.models import Order, OrderStatus
from marche.services import inventory, payment
from marche.services.payment import PaymentError


@pytest.fixture
def order(customer, make_product):
    product = make_product(price=300, stock=5)
    order = inventory.create_order(customer, {product.id: 2})
    order.stripe_checkout_session_id = f"cs_test_fake_{order.id}"
    db.session.commit()
    return order


def test_決済作成失敗は注文を取り消しカートを残す(
    client, customer, login, make_product, fake_payment
):
    product = make_product(stock=5)
    login(customer)
    client.post(f"/cart/add/{product.id}", data={"quantity": 2})
    fake_payment.error = PaymentError("決済を開始できません")
    response = client.post("/orders/", follow_redirects=True)
    order = db.session.scalar(db.select(Order))
    assert order.status == OrderStatus.CANCELLED
    assert order.stripe_checkout_session_id is None
    assert inventory.available_stock(product) == 5
    assert "決済を開始できません" in response.text
    with client.session_transaction() as session:
        assert session["cart"] == {str(product.id): 2}


@pytest.mark.parametrize("viewer", ["customer", "admin"])
def test_本人と管理者は中断表示と取消ができる(
    client, order, login, request, viewer, fake_payment
):
    login(request.getfixturevalue(viewer))
    response = client.get(f"/orders/{order.id}/cancel")
    assert response.status_code == 200
    assert "この注文を取り消す" in response.text
    assert order.status == OrderStatus.PENDING
    assert fake_payment.expired == []
    response = client.post(f"/orders/{order.id}/cancel")
    assert response.headers["Location"] == f"/orders/{order.id}"
    assert order.status == OrderStatus.CANCELLED
    assert fake_payment.expired == [order.stripe_checkout_session_id]
    assert inventory.available_stock(order.items[0].product) == 5


def test_Session失効失敗では注文も在庫の予約も維持する(
    client, order, customer, login, fake_payment
):
    login(customer)
    fake_payment.error = PaymentError("この注文は取り消せませんでした")
    response = client.post(f"/orders/{order.id}/cancel", follow_redirects=True)
    assert "取り消せませんでした" in response.text
    assert fake_payment.expired == [order.stripe_checkout_session_id]
    assert order.status == OrderStatus.PENDING
    assert inventory.available_stock(order.items[0].product) == 3


@pytest.mark.parametrize("status", [OrderStatus.PAID, OrderStatus.CANCELLED])
def test_支払い待ち以外は取り消しもSession失効もしない(
    client, order, customer, login, fake_payment, status
):
    order.status = status
    db.session.commit()
    login(customer)
    client.post(f"/orders/{order.id}/cancel")
    assert order.status == status
    assert fake_payment.expired == []


def test_Session無しの支払い待ちも取り消せる(
    client, order, customer, login, fake_payment
):
    order.stripe_checkout_session_id = None
    db.session.commit()
    login(customer)
    client.post(f"/orders/{order.id}/cancel")
    assert order.status == OrderStatus.CANCELLED
    assert fake_payment.expired == []


@pytest.mark.parametrize("viewer", ["customer", "admin"])
def test_確認画面は本人と管理者が見られ状態を変えない(
    client, order, login, request, viewer, fake_payment
):
    login(request.getfixturevalue(viewer))
    response = client.get(f"/orders/{order.id}/complete?session_id=untrusted")
    assert response.status_code == 200
    assert "お支払いを確認しています" in response.text
    assert order.status == OrderStatus.PENDING
    assert order.paid_at is None
    assert order.items[0].product.stock == 5
    assert fake_payment.retrieved == []


@pytest.mark.parametrize(
    "method,path", [("get", "complete"), ("get", "cancel"), ("post", "cancel")]
)
@pytest.mark.parametrize("viewer", [None, "other_producer"])
def test_未ログインと他人は確認も取消もできない(
    client, order, login, request, viewer, method, path, fake_payment
):
    if viewer:
        login(request.getfixturevalue(viewer))
    response = getattr(client, method)(f"/orders/{order.id}/{path}")
    assert response.status_code == (403 if viewer else 302)
    if not viewer:
        assert "/login" in response.headers["Location"]
    assert order.status == OrderStatus.PENDING
    assert order.stripe_checkout_session_id == f"cs_test_fake_{order.id}"
    assert fake_payment.expired == []


@pytest.mark.parametrize(
    "method,path", [("get", "complete"), ("get", "cancel"), ("post", "cancel")]
)
def test_存在しない注文の確認と取消は404(client, customer, login, method, path):
    login(customer)
    assert getattr(client, method)(f"/orders/999/{path}").status_code == 404


def test_取消POSTはCSRFを必要とする(app, client, order, customer, login, fake_payment):
    login(customer)
    app.config["WTF_CSRF_ENABLED"] = True
    assert client.post(f"/orders/{order.id}/cancel").status_code == 400
    assert order.status == OrderStatus.PENDING
    assert fake_payment.expired == []


def test_中断画面のCSRFで取消できSession失効を先に行う(
    app, client, order, customer, login, fake_payment, monkeypatch
):
    login(customer)
    app.config["WTF_CSRF_ENABLED"] = True
    response = client.get(f"/orders/{order.id}/cancel")
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    original_expire = fake_payment.expire_session

    def expire_before_cancel(session_id):
        assert order.status == OrderStatus.PENDING
        assert inventory.available_stock(order.items[0].product) == 3
        original_expire(session_id)

    monkeypatch.setattr(fake_payment, "expire_session", expire_before_cancel)
    response = client.post(f"/orders/{order.id}/cancel", data={"csrf_token": token})
    assert response.status_code == 302
    assert order.status == OrderStatus.CANCELLED
    assert fake_payment.expired == [order.stripe_checkout_session_id]


@pytest.fixture
def stripe_sessions(monkeypatch):
    sessions = Mock()
    monkeypatch.setattr(
        payment,
        "_client",
        lambda: SimpleNamespace(
            v1=SimpleNamespace(checkout=SimpleNamespace(sessions=sessions))
        ),
    )
    return sessions


def test_Stripeには保存済み明細の円価格と正しい戻り先を渡す(
    app, order, stripe_sessions, monkeypatch
):
    order.items[0].product.price = 9999
    order.items[0].product.name = "変更後"
    db.session.commit()
    monkeypatch.setattr(payment.time, "time", lambda: 1_800_000_000)
    stripe_sessions.create.return_value = SimpleNamespace(
        id="cs_test_created", url="https://checkout.stripe.test/created"
    )
    with app.test_request_context(base_url="https://marche.example"):
        assert payment.create_checkout_session(order) == (
            "cs_test_created",
            "https://checkout.stripe.test/created",
        )
    params = stripe_sessions.create.call_args.args[0]
    assert params["line_items"] == [
        {
            "quantity": 2,
            "price_data": {
                "currency": "jpy",
                "unit_amount": 300,
                "product_data": {"name": "ほうれん草"},
            },
        }
    ]
    assert params["metadata"] == {"order_id": str(order.id)}
    assert params["customer_email"] == order.user.email
    assert params["mode"] == "payment"
    assert params["expires_at"] == 1_800_000_000 + 31 * 60
    assert (
        params["success_url"]
        == f"https://marche.example/orders/{order.id}/complete?session_id={{CHECKOUT_SESSION_ID}}"
    )
    assert params["cancel_url"] == f"https://marche.example/orders/{order.id}/cancel"


def test_Stripeの取得と失効は指定Sessionだけに行う(app, stripe_sessions):
    stripe_sessions.retrieve.return_value = {"id": "cs_test_one"}
    assert payment.retrieve_session("cs_test_one") == {"id": "cs_test_one"}
    payment.expire_session("cs_test_one")
    stripe_sessions.retrieve.assert_called_once_with("cs_test_one")
    stripe_sessions.expire.assert_called_once_with("cs_test_one")


@pytest.mark.parametrize("operation", ["create", "retrieve", "expire"])
def test_Stripeの例外を画面用エラーに変換する(
    app, order, stripe_sessions, operation, caplog
):
    getattr(stripe_sessions, operation).side_effect = stripe.StripeError(
        "sensitive-provider-error"
    )
    with app.test_request_context(), pytest.raises(PaymentError):
        if operation == "create":
            payment.create_checkout_session(order)
        elif operation == "retrieve":
            payment.retrieve_session("cs_test_one")
        else:
            payment.expire_session("cs_test_one")
    assert "sensitive-provider-error" not in caplog.text


def test_キー未設定は外部通信せず設定エラー(app):
    app.config["STRIPE_SECRET_KEY"] = ""
    with pytest.raises(PaymentError, match="設定"):
        payment._client()

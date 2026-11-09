import pytest

from marche.extensions import db
from marche.models import Order, OrderStatus
from marche.services.inventory import OrderError, create_order


def all_orders():
    return db.session.scalars(db.select(Order)).all()


def put_in_cart(client, product, quantity):
    client.post(f"/cart/add/{product.id}", data={"quantity": str(quantity)})


# --- 注文（正常、T9） ---


def test_カートから注文を作れる(
    client, producer, customer, login, make_product, fake_payment
):
    tomato = make_product(producer, name="トマト", price=300)
    miso = make_product(producer, name="味噌", price=1300)
    login(customer)
    put_in_cart(client, tomato, 2)
    put_in_cart(client, miso, 1)
    response = client.post("/orders/")
    order = all_orders()[0]
    assert response.status_code == 303
    assert (
        response.headers["Location"]
        == f"https://checkout.stripe.test/cs_test_fake_{order.id}"
    )
    assert order.stripe_checkout_session_id == f"cs_test_fake_{order.id}"
    assert fake_payment.created == [order.id]
    assert order.user_id == customer.id
    assert order.status == OrderStatus.PENDING
    assert order.total_amount == 300 * 2 + 1300
    assert {(i.product_name, i.unit_price, i.quantity) for i in order.items} == {
        ("トマト", 300, 2),
        ("味噌", 1300, 1),
    }
    with client.session_transaction() as session:
        assert "cart" not in session  # 注文したらカートは空になる


def test_フォームに金額を混ぜても無視される(
    client, producer, customer, login, make_product
):
    product = make_product(producer, price=300)
    login(customer)
    put_in_cart(client, product, 2)
    client.post("/orders/", data={"total_amount": "1", "price": "1"})
    assert all_orders()[0].total_amount == 600


def test_注文後に価格が変わっても明細は変わらない(
    client, producer, customer, login, make_product
):
    product = make_product(producer, name="トマト", price=300)
    login(customer)
    put_in_cart(client, product, 1)
    client.post("/orders/")
    product.name = "高級トマト"
    product.price = 900
    db.session.commit()
    order = all_orders()[0]
    text = client.get(f"/orders/{order.id}").text
    assert "トマト" in text and "高級トマト" not in text
    assert "300円" in text


def test_未ログインでは注文できない(client, producer, make_product):
    product = make_product(producer)
    put_in_cart(client, product, 1)
    response = client.post("/orders/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert all_orders() == []


def test_カートが空なら注文できない(client, customer, login):
    login(customer)
    client.post("/orders/")
    assert all_orders() == []


# --- 注文（在庫・非公開、T10） ---


def test_在庫を超える数は注文できない(app, producer, customer, make_product):
    product = make_product(producer, stock=2)
    with pytest.raises(OrderError):
        create_order(customer, {product.id: 3})
    assert all_orders() == []


def test_非公開の商品は注文できない(app, producer, customer, make_product):
    product = make_product(producer, is_published=False)
    with pytest.raises(OrderError):
        create_order(customer, {product.id: 1})
    assert all_orders() == []


def test_無い商品は注文できない(app, customer):
    with pytest.raises(OrderError):
        create_order(customer, {999: 1})
    assert all_orders() == []


def test_数量が範囲外なら注文できない(app, producer, customer, make_product):
    product = make_product(producer)
    for quantity in (0, 11, -1):
        with pytest.raises(OrderError):
            create_order(customer, {product.id: quantity})
    assert all_orders() == []


def test_カートに入れた後に在庫が減ったら注文できない(
    client, producer, customer, login, make_product
):
    product = make_product(producer, stock=5)
    login(customer)
    put_in_cart(client, product, 3)
    product.stock = 2
    db.session.commit()
    response = client.post("/orders/", follow_redirects=True)
    assert "在庫が足りません" in response.text
    assert all_orders() == []


def test_支払い待ちの注文は在庫を押さえる(app, producer, customer, make_product):
    product = make_product(producer, stock=3)
    create_order(customer, {product.id: 2})
    with pytest.raises(OrderError):
        create_order(customer, {product.id: 2})


# --- 注文詳細と他人の注文（T12） ---


def test_自分の注文詳細を見られる(client, producer, customer, login, make_product):
    product = make_product(producer)
    order = create_order(customer, {product.id: 1})
    login(customer)
    response = client.get(f"/orders/{order.id}")
    assert response.status_code == 200
    assert "支払い待ち" in response.text


def test_他人の注文詳細は403(
    client, producer, customer, other_producer, login, make_product
):
    product = make_product(producer)
    order = create_order(customer, {product.id: 1})
    login(other_producer)
    assert client.get(f"/orders/{order.id}").status_code == 403


def test_管理者は他人の注文詳細を見られる(
    client, producer, customer, admin, login, make_product
):
    product = make_product(producer)
    order = create_order(customer, {product.id: 1})
    login(admin)
    assert client.get(f"/orders/{order.id}").status_code == 200


def test_未ログインでは注文詳細を見られない(client, producer, customer, make_product):
    product = make_product(producer)
    order = create_order(customer, {product.id: 1})
    response = client.get(f"/orders/{order.id}")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_無い注文は404(client, customer, login):
    login(customer)
    assert client.get("/orders/999").status_code == 404

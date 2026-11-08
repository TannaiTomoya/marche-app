"""#5 注文履歴、#6 売上、#7 seed、#8 413、#9 管理者の注文一覧"""

import io

from marche.extensions import db
from marche.models import Order, OrderItem, OrderStatus, Product, User


def add_order(user, product, quantity, status):
    order = Order(
        user_id=user.id,
        status=status,
        total_amount=product.price * quantity,
        items=[
            OrderItem(
                product_id=product.id,
                product_name=product.name,
                unit_price=product.price,
                quantity=quantity,
                subtotal=product.price * quantity,
            )
        ],
    )
    db.session.add(order)
    db.session.commit()
    return order


# --- #5 注文履歴 ---


def test_注文履歴には自分の注文だけが出る(
    client, producer, customer, other_producer, login, make_product
):
    product = make_product(producer, price=450)
    mine = add_order(customer, product, 2, OrderStatus.PAID)
    others = add_order(other_producer, product, 1, OrderStatus.PENDING)
    login(customer)
    response = client.get("/orders/")
    assert response.status_code == 200
    assert f'href="/orders/{mine.id}"' in response.text
    assert f'href="/orders/{others.id}"' not in response.text
    assert "900円" in response.text
    assert "支払い済み" in response.text


def test_未ログインでは注文履歴を見られない(client):
    response = client.get("/orders/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# --- #6 売上（T23） ---


def test_売上は自分の商品の支払い済みだけを集計する(
    client, producer, other_producer, customer, login, make_product
):
    tomato = make_product(producer, name="トマト", price=300)
    others = make_product(other_producer, name="他人のりんご", price=500)
    add_order(customer, tomato, 2, OrderStatus.PAID)
    add_order(customer, tomato, 1, OrderStatus.PAID)
    add_order(customer, tomato, 5, OrderStatus.PENDING)
    add_order(customer, tomato, 7, OrderStatus.CANCELLED)
    add_order(customer, others, 3, OrderStatus.PAID)
    login(producer)
    response = client.get("/producer/sales")
    assert response.status_code == 200
    text = response.text
    assert "トマト" in text
    assert "900円" in text  # 300円 × (2 + 1)
    assert "他人のりんご" not in text
    assert "1,500円" not in text


def test_売上は注文時点の単価で計算する(
    client, producer, customer, login, make_product
):
    tomato = make_product(producer, price=300)
    add_order(customer, tomato, 2, OrderStatus.PAID)
    tomato.price = 1000
    db.session.commit()
    login(producer)
    assert "600円" in client.get("/producer/sales").text


def test_購入者は売上を見られない(client, customer, login):
    login(customer)
    assert client.get("/producer/sales").status_code == 403


def test_未ログインでは売上を見られない(client):
    response = client.get("/producer/sales")
    assert response.status_code == 302


# --- #7 seed（T24） ---


def test_seedで初期データが入り2回実行しても件数は同じ(app):
    runner = app.test_cli_runner()
    for _ in range(2):
        result = runner.invoke(args=["seed"])
        assert result.exit_code == 0, result.output
    assert len(db.session.scalars(db.select(User)).all()) == 5
    products = db.session.scalars(db.select(Product)).all()
    assert len(products) == 8
    assert sum(1 for p in products if not p.is_published) == 1


def test_seedは開発とテスト以外では動かない(app):
    app.testing = False
    app.debug = False
    result = app.test_cli_runner().invoke(args=["seed"])
    assert result.exit_code != 0
    assert db.session.scalars(db.select(User)).all() == []


# --- #8 大きすぎるファイル ---


def test_6MBを超えるファイルは日本語の413画面になる(client, producer, login):
    login(producer)
    data = {
        "name": "大きい写真",
        "price": "450",
        "stock": "1",
        "image": (io.BytesIO(b"0" * (7 * 1024 * 1024)), "big.png"),
    }
    response = client.post(
        "/producer/products/new", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 413
    assert "5MB 以下" in response.text
    assert db.session.scalars(db.select(Product)).all() == []


# --- #9 管理者の注文一覧 ---


def test_管理者は全員の注文を見られる(
    client, admin, producer, customer, other_producer, login, make_product
):
    product = make_product(producer)
    first = add_order(customer, product, 1, OrderStatus.PAID)
    second = add_order(other_producer, product, 1, OrderStatus.PENDING)
    login(admin)
    response = client.get("/admin/orders")
    assert response.status_code == 200
    assert f'href="/orders/{first.id}"' in response.text
    assert f'href="/orders/{second.id}"' in response.text


def test_管理者の注文一覧は状態で絞り込める(
    client, admin, producer, customer, login, make_product
):
    product = make_product(producer)
    paid = add_order(customer, product, 1, OrderStatus.PAID)
    pending = add_order(customer, product, 1, OrderStatus.PENDING)
    login(admin)
    text = client.get("/admin/orders?status=paid").text
    assert f'href="/orders/{paid.id}"' in text
    assert f'href="/orders/{pending.id}"' not in text


def test_管理者以外は注文一覧を見られない(client, customer, producer, login):
    assert client.get("/admin/orders").status_code == 302  # 未ログイン
    login(customer)
    assert client.get("/admin/orders").status_code == 403
    login(producer)
    assert client.get("/admin/orders").status_code == 403

from datetime import timedelta

from marche.extensions import db
from marche.models import Order, OrderItem, OrderStatus, now_jst
from marche.services.inventory import available_stock


def add_order(user, product, quantity, status=OrderStatus.PENDING, minutes_ago=0):
    order = Order(
        user_id=user.id,
        status=status,
        total_amount=product.price * quantity,
        created_at=now_jst() - timedelta(minutes=minutes_ago),
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


# --- 一覧と詳細（T8） ---


def test_一覧には公開中の商品だけが出る(client, producer, make_product):
    make_product(producer, name="公開のトマト", price=1200)
    make_product(producer, name="準備中のなす", is_published=False)
    text = client.get("/").text
    assert "公開のトマト" in text
    assert "1,200円" in text
    assert "高原ファーム" in text
    assert "準備中のなす" not in text


def test_在庫0の商品は売り切れと出る(client, producer, make_product):
    product = make_product(producer, stock=0)
    assert "売り切れ" in client.get("/").text
    detail = client.get(f"/products/{product.id}").text
    assert "売り切れ" in detail
    assert "カートに入れる" not in detail


def test_公開中の商品の詳細は誰でも見られる(client, producer, make_product):
    product = make_product(producer, description="朝採りです")
    response = client.get(f"/products/{product.id}")
    assert response.status_code == 200
    assert "朝採りです" in response.text
    assert "カートに入れる" in response.text


def test_非公開の商品の詳細は出品者以外404(
    client, producer, other_producer, customer, login, make_product
):
    product = make_product(producer, is_published=False)
    url = f"/products/{product.id}"
    assert client.get(url).status_code == 404  # 未ログイン
    login(customer)
    assert client.get(url).status_code == 404
    login(other_producer)
    assert client.get(url).status_code == 404


def test_非公開の商品の詳細は出品者と管理者には見える(
    client, producer, admin, login, make_product
):
    product = make_product(producer, is_published=False)
    url = f"/products/{product.id}"
    login(producer)
    assert client.get(url).status_code == 200
    login(admin)
    assert client.get(url).status_code == 200


def test_無い商品の詳細は404(client):
    assert client.get("/products/999").status_code == 404


def test_紹介文のHTMLはエスケープされる(client, producer, make_product):
    product = make_product(producer, description="<script>alert(1)</script>")
    text = client.get(f"/products/{product.id}").text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


# --- 在庫の押さえ（T11） ---


def test_支払い待ちの数だけいま買える数が減る(app, producer, customer, make_product):
    product = make_product(producer, stock=10)
    add_order(customer, product, 3)
    assert available_stock(product) == 7


def test_35分を過ぎた支払い待ちは引かない(app, producer, customer, make_product):
    product = make_product(producer, stock=10)
    add_order(customer, product, 3, minutes_ago=36)
    assert available_stock(product) == 10


def test_支払い済みと取り消しは引かない(app, producer, customer, make_product):
    # 支払い済みの分は、確定時に stock から減らしてある
    product = make_product(producer, stock=10)
    add_order(customer, product, 2, status=OrderStatus.PAID)
    add_order(customer, product, 2, status=OrderStatus.CANCELLED)
    assert available_stock(product) == 10


def test_いま買える数は0未満にならない(app, producer, customer, make_product):
    product = make_product(producer, stock=5)
    add_order(customer, product, 5)
    product.stock = 2  # 生産者が在庫を減らした
    db.session.commit()
    assert available_stock(product) == 0

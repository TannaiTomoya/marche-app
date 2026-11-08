import io
import os

from marche.extensions import db
from marche.models import Order, OrderItem, OrderStatus, Product

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def product_data(**kwargs):
    data = {
        "name": "八幡平マッシュルーム 200g",
        "price": "450",
        "stock": "20",
        "description": "朝採りです",
    }
    data.update(kwargs)
    return data


def count_products():
    return len(db.session.scalars(db.select(Product)).all())


# --- ロールの確認（T3） ---


def test_未ログインで出品管理を開くとログインへ(client):
    response = client.get("/producer/products")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_購入者は出品管理を開けない(client, customer, login):
    login(customer)
    assert client.get("/producer/products").status_code == 403
    assert client.get("/producer/products/new").status_code == 403


def test_購入者は商品を登録できない(client, customer, login):
    login(customer)
    response = client.post("/producer/products/new", data=product_data())
    assert response.status_code == 403
    assert count_products() == 0


# --- 商品の登録（T4） ---


def test_生産者は商品を登録できる(client, producer, login):
    login(producer)
    response = client.post("/producer/products/new", data=product_data())
    assert response.status_code == 302
    product = db.session.scalar(db.select(Product))
    assert product.name == "八幡平マッシュルーム 200g"
    assert product.price == 450
    assert product.producer_id == producer.id
    assert product.is_published is False  # 印を付けなければ非公開


def test_価格が50円未満なら登録できない(client, producer, login):
    login(producer)
    response = client.post("/producer/products/new", data=product_data(price="49"))
    assert response.status_code == 422
    assert count_products() == 0


def test_商品名が無いと登録できない(client, producer, login):
    login(producer)
    response = client.post("/producer/products/new", data=product_data(name=""))
    assert response.status_code == 422
    assert count_products() == 0


# --- 写真（T6） ---


def test_PNGの写真を登録できる(app, client, producer, login):
    login(producer)
    data = product_data(image=(io.BytesIO(PNG), "photo.png"))
    response = client.post(
        "/producer/products/new", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 302
    product = db.session.scalar(db.select(Product))
    assert product.image_filename.endswith(".png")
    assert product.image_filename != "photo.png"  # ファイル名はサーバーで付け直す
    assert os.path.exists(
        os.path.join(app.config["UPLOAD_FOLDER"], product.image_filename)
    )


def test_中身が画像でなければ登録できない(client, producer, login):
    login(producer)
    data = product_data(image=(io.BytesIO(b"<script>alert(1)</script>"), "photo.png"))
    response = client.post(
        "/producer/products/new", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 422
    assert count_products() == 0


def test_GIFは登録できない(client, producer, login):
    login(producer)
    data = product_data(image=(io.BytesIO(b"GIF89a" + b"\x00" * 10), "photo.gif"))
    response = client.post(
        "/producer/products/new", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 422
    assert count_products() == 0


def test_5MBを超える写真は登録できない(client, producer, login):
    login(producer)
    big = PNG + b"\x00" * (5 * 1024 * 1024)
    data = product_data(image=(io.BytesIO(big), "big.png"))
    response = client.post(
        "/producer/products/new", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 422
    assert count_products() == 0


# --- 編集と他人の商品（T5） ---


def test_自分の商品を編集できる(client, producer, login, make_product):
    product = make_product(producer)
    login(producer)
    response = client.post(
        f"/producer/products/{product.id}/edit",
        data=product_data(name="ほうれん草 2束", price="300"),
    )
    assert response.status_code == 302
    assert product.name == "ほうれん草 2束"
    assert product.price == 300


def test_他人の商品は編集できない(
    client, producer, other_producer, login, make_product
):
    product = make_product(producer)
    login(other_producer)
    assert client.get(f"/producer/products/{product.id}/edit").status_code == 403
    response = client.post(
        f"/producer/products/{product.id}/edit", data=product_data(name="乗っ取り")
    )
    assert response.status_code == 403
    db.session.refresh(product)
    assert product.name == "ほうれん草 1束"


def test_他人の商品は削除できない(
    client, producer, other_producer, login, make_product
):
    product = make_product(producer)
    login(other_producer)
    response = client.post(f"/producer/products/{product.id}/delete")
    assert response.status_code == 403
    assert db.session.get(Product, product.id) is not None


def test_他人の商品の公開を切り替えられない(
    client, producer, other_producer, login, make_product
):
    product = make_product(producer, is_published=False)
    login(other_producer)
    response = client.post(f"/producer/products/{product.id}/toggle")
    assert response.status_code == 403
    db.session.refresh(product)
    assert product.is_published is False


def test_無い商品の編集は404(client, producer, login):
    login(producer)
    assert client.get("/producer/products/999/edit").status_code == 404


# --- 公開の切り替え（T7）と削除 ---


def test_非公開から公開に切り替えられる(client, producer, login, make_product):
    product = make_product(producer, is_published=False)
    login(producer)
    response = client.post(f"/producer/products/{product.id}/toggle")
    assert response.status_code == 302
    assert product.is_published is True


def test_自分の商品を削除できる(client, producer, login, make_product):
    product = make_product(producer)
    product_id = product.id
    login(producer)
    response = client.post(f"/producer/products/{product_id}/delete")
    assert response.status_code == 302
    assert db.session.get(Product, product_id) is None


def test_注文がある商品は削除できない(client, producer, customer, login, make_product):
    product = make_product(producer)
    order = Order(
        user_id=customer.id,
        status=OrderStatus.PAID,
        total_amount=180,
        items=[
            OrderItem(
                product_id=product.id,
                product_name=product.name,
                unit_price=180,
                quantity=1,
                subtotal=180,
            )
        ],
    )
    db.session.add(order)
    db.session.commit()
    login(producer)
    client.post(f"/producer/products/{product.id}/delete")
    assert db.session.get(Product, product.id) is not None


def test_出品管理には自分の商品だけが出る(
    client, producer, other_producer, login, make_product
):
    make_product(producer, name="自分のトマト")
    make_product(other_producer, name="他人のりんご")
    login(producer)
    text = client.get("/producer/products").text
    assert "自分のトマト" in text
    assert "他人のりんご" not in text

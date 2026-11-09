import io
import os
import re

import pytest

from marche.extensions import db
from marche.models import Order, OrderItem, OrderStatus, Product
from marche.uploads import detect_media_type

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
    data = product_data(image=(io.BytesIO(b"<?php echo 1; ?>"), "photo.png"))
    response = client.post(
        "/producer/products/new", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 422
    assert "画像として読み込めない" in response.text
    assert count_products() == 0


def test_GIFは登録できない(client, producer, login):
    login(producer)
    data = product_data(image=(io.BytesIO(b"GIF89a" + b"\x00" * 10), "photo.gif"))
    response = client.post(
        "/producer/products/new", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 422
    assert "JPEG / PNG / WebP の画像を選んでください" in response.text
    assert count_products() == 0


def test_拡張子を変えたGIFも中身で弾かれる(client, producer, login):
    login(producer)
    data = product_data(image=(io.BytesIO(b"GIF89a" + b"\x00" * 10), "photo.jpg"))
    response = client.post(
        "/producer/products/new", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 422
    assert "画像として読み込めない" in response.text
    assert count_products() == 0


def test_5MBを超える写真は登録できない(client, producer, login):
    login(producer)
    big = PNG + b"\x00" * (5 * 1024 * 1024)
    data = product_data(image=(io.BytesIO(big), "big.png"))
    response = client.post(
        "/producer/products/new", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 422
    assert "5MB 以下の画像を選んでください" in response.text
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
    assert product.name == "ほうれん草"


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


def test_写真を差し替えると古いファイルが消える(app, client, producer, login):
    login(producer)
    client.post(
        "/producer/products/new",
        data=product_data(image=(io.BytesIO(PNG), "a.png")),
        content_type="multipart/form-data",
    )
    product = db.session.scalar(db.select(Product))
    old_path = os.path.join(app.config["UPLOAD_FOLDER"], product.image_filename)
    assert os.path.exists(old_path)
    client.post(
        f"/producer/products/{product.id}/edit",
        data=product_data(image=(io.BytesIO(PNG), "b.png")),
        content_type="multipart/form-data",
    )
    db.session.refresh(product)
    assert not os.path.exists(old_path)
    new_path = os.path.join(app.config["UPLOAD_FOLDER"], product.image_filename)
    assert os.path.exists(new_path)


def test_商品を削除すると写真も消える(app, client, producer, login):
    login(producer)
    client.post(
        "/producer/products/new",
        data=product_data(image=(io.BytesIO(PNG), "a.png")),
        content_type="multipart/form-data",
    )
    product = db.session.scalar(db.select(Product))
    path = os.path.join(app.config["UPLOAD_FOLDER"], product.image_filename)
    client.post(f"/producer/products/{product.id}/delete")
    assert not os.path.exists(path)


def test_detect_media_typeは中身で種類を判定する():
    assert detect_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert detect_media_type(PNG) == "image/png"
    assert detect_media_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert detect_media_type(b"GIF89a") is None
    assert detect_media_type(b"") is None


# --- レビューの指摘で足したテスト ---


def uploaded_files(app):
    folder = app.config["UPLOAD_FOLDER"]
    return os.listdir(folder) if os.path.exists(folder) else []


def test_弾いたファイルは保存されない(app, client, producer, login):
    login(producer)
    for content, name in [(b"<?php echo 1; ?>", "photo.png"), (b"GIF89a", "a.gif")]:
        client.post(
            "/producer/products/new",
            data=product_data(image=(io.BytesIO(content), name)),
            content_type="multipart/form-data",
        )
    assert uploaded_files(app) == []


def test_編集で不正な画像を送ると422で商品と写真は変わらない(
    app, client, producer, login
):
    login(producer)
    client.post(
        "/producer/products/new",
        data=product_data(image=(io.BytesIO(PNG), "a.png")),
        content_type="multipart/form-data",
    )
    product = db.session.scalar(db.select(Product))
    old_filename = product.image_filename
    response = client.post(
        f"/producer/products/{product.id}/edit",
        data=product_data(name="変えた名前", image=(io.BytesIO(b"not image"), "b.png")),
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    db.session.refresh(product)
    assert product.name == "八幡平マッシュルーム 200g"
    assert product.image_filename == old_filename
    assert uploaded_files(app) == [old_filename]


def test_ファイル名にパスを入れても一時フォルダーの中にランダムな名前で保存される(
    app, client, producer, login
):
    login(producer)
    client.post(
        "/producer/products/new",
        data=product_data(image=(io.BytesIO(PNG), "../../evil.png")),
        content_type="multipart/form-data",
    )
    product = db.session.scalar(db.select(Product))
    assert re.fullmatch(r"[0-9a-f]{32}\.png", product.image_filename)
    assert uploaded_files(app) == [product.image_filename]


def test_他人の商品の削除が403なら写真も消えない(
    app, client, producer, other_producer, login
):
    login(producer)
    client.post(
        "/producer/products/new",
        data=product_data(image=(io.BytesIO(PNG), "a.png")),
        content_type="multipart/form-data",
    )
    product = db.session.scalar(db.select(Product))
    login(other_producer)
    assert client.post(f"/producer/products/{product.id}/delete").status_code == 403
    assert uploaded_files(app) == [product.image_filename]


def test_保存に失敗したら新しい写真を消す(app, client, producer, login, monkeypatch):
    login(producer)

    def broken_commit():
        raise RuntimeError("データベースに書き込めない")

    monkeypatch.setattr(db.session, "commit", broken_commit)
    with pytest.raises(RuntimeError):
        client.post(
            "/producer/products/new",
            data=product_data(image=(io.BytesIO(PNG), "a.png")),
            content_type="multipart/form-data",
        )
    assert uploaded_files(app) == []

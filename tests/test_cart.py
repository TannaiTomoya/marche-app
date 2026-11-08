from marche.extensions import db


def cart_of(client):
    with client.session_transaction() as session:
        return session.get("cart", {})


def test_未ログインでもカートに入れられる(client, producer, make_product):
    product = make_product(producer, price=180)
    response = client.post(f"/cart/add/{product.id}", data={"quantity": "2"})
    assert response.status_code == 302
    assert cart_of(client) == {str(product.id): 2}
    text = client.get("/cart/").text
    assert "ほうれん草" in text
    assert "360円" in text


def test_同じ商品を入れると数量が足される(client, producer, make_product):
    product = make_product(producer)
    client.post(f"/cart/add/{product.id}", data={"quantity": "2"})
    client.post(f"/cart/add/{product.id}", data={"quantity": "3"})
    assert cart_of(client) == {str(product.id): 5}


def test_数量を変えられる(client, producer, make_product):
    product = make_product(producer)
    client.post(f"/cart/add/{product.id}", data={"quantity": "2"})
    client.post(f"/cart/update/{product.id}", data={"quantity": "4"})
    assert cart_of(client) == {str(product.id): 4}


def test_数量0でカートから外せる(client, producer, make_product):
    product = make_product(producer)
    client.post(f"/cart/add/{product.id}", data={"quantity": "2"})
    client.post(f"/cart/update/{product.id}", data={"quantity": "0"})
    assert cart_of(client) == {}


def test_非公開の商品はカートに入れられない(client, producer, make_product):
    product = make_product(producer, is_published=False)
    response = client.post(f"/cart/add/{product.id}", data={"quantity": "1"})
    assert response.status_code == 404
    assert cart_of(client) == {}


def test_11個以上は入れられない(client, producer, make_product):
    product = make_product(producer)
    client.post(f"/cart/add/{product.id}", data={"quantity": "11"})
    assert cart_of(client) == {}
    client.post(f"/cart/add/{product.id}", data={"quantity": "6"})
    client.post(f"/cart/add/{product.id}", data={"quantity": "5"})
    assert cart_of(client) == {str(product.id): 6}


def test_在庫を超える数は入れられない(client, producer, make_product):
    product = make_product(producer, stock=2)
    client.post(f"/cart/add/{product.id}", data={"quantity": "3"})
    assert cart_of(client) == {}


def test_数量が数字でなければ入れられない(client, producer, make_product):
    product = make_product(producer)
    client.post(f"/cart/add/{product.id}", data={"quantity": "abc"})
    assert cart_of(client) == {}


def test_非公開になった商品はカートの表示から外れる(client, producer, make_product):
    product = make_product(producer)
    client.post(f"/cart/add/{product.id}", data={"quantity": "1"})
    product.is_published = False
    db.session.commit()
    assert "カートは空です" in client.get("/cart/").text
    assert cart_of(client) == {}

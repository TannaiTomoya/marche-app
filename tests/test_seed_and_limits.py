"""初期データ（04 章の flask seed）と、大きすぎるファイル（03 章の 413）"""

import io

from marche.extensions import db
from marche.models import Product, User

# --- flask seed（04 章） ---


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


# --- 大きすぎるファイル（03 章） ---


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

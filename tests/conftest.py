from types import SimpleNamespace

import pytest

from marche import create_app
from marche.extensions import db
from marche.models import Product, Role, User

# 本物の外部サービス（Stripe、拡張で足す Claude API）は、テストでは呼ばない。
# フェイク（偽物）のクラスを create_app() の設定で渡して差し替える。

WEBHOOK_SECRET = "whsec_test"


class FakePayment:
    """services/payment.py と同じ名前の関数を持つ偽物。呼ばれた引数を記録する"""

    def __init__(self):
        self.calls = []
        self.error = None  # 例外を入れると create_checkout_session が失敗する
        self.expire_error = None
        self.payment_status = "paid"

    def create_checkout_session(self, order):
        self.calls.append(("create", order.id))
        if self.error:
            raise self.error
        return f"cs_test_{order.id}", f"https://checkout.stripe.test/{order.id}"

    def retrieve_session(self, session_id):
        self.calls.append(("retrieve", session_id))
        return SimpleNamespace(
            id=session_id,
            payment_status=self.payment_status,
            payment_intent=f"pi_test_{session_id}",
        )

    def expire_session(self, session_id):
        self.calls.append(("expire", session_id))
        if self.expire_error:
            raise self.expire_error


@pytest.fixture
def fake_payment():
    return FakePayment()


@pytest.fixture
def app(tmp_path, fake_payment):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            # 写真はテストごとの一時フォルダーに保存する（本物の static/uploads を汚さない）
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "STRIPE_WEBHOOK_SECRET": WEBHOOK_SECRET,
            "PAYMENT_SERVICE": fake_payment,
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def _make_user(role, email, name):
    user = User(name=name, email=email, role=role)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def customer(app):
    return _make_user(Role.CUSTOMER, "customer@example.com", "購入者")


@pytest.fixture
def producer(app):
    return _make_user(Role.PRODUCER, "producer@example.com", "高原ファーム")


@pytest.fixture
def other_producer(app):
    return _make_user(Role.PRODUCER, "other@example.com", "別の農園")


@pytest.fixture
def admin(app):
    return _make_user(Role.ADMIN, "admin@example.com", "管理者")


@pytest.fixture
def make_product(app):
    def do_make(producer, **kwargs):
        values = {
            "name": "ほうれん草 1束",
            "price": 180,
            "stock": 30,
            "is_published": True,
        }
        values.update(kwargs)
        product = Product(producer_id=producer.id, **values)
        db.session.add(product)
        db.session.commit()
        return product

    return do_make


@pytest.fixture
def login(client):
    def do_login(user):
        return client.post("/login", data={"email": user.email, "password": "password"})

    return do_login

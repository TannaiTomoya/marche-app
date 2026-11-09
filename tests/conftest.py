import pytest

from marche import create_app
from marche.extensions import db
from marche.models import Product, Role, User


class FakePayment:
    """本物のStripeを呼ばず、呼び出しと失敗を検証する。"""

    def __init__(self):
        self.created = []
        self.expired = []
        self.retrieved = []
        self.sessions = {}
        self.error = None

    def create_checkout_session(self, order):
        if self.error:
            raise self.error
        self.created.append(order.id)
        session_id = f"cs_test_fake_{order.id}"
        return session_id, f"https://checkout.stripe.test/{session_id}"

    def retrieve_session(self, session_id):
        self.retrieved.append(session_id)
        if self.error:
            raise self.error
        return self.sessions[session_id]

    def expire_session(self, session_id):
        self.expired.append(session_id)
        if self.error:
            raise self.error


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
def make_product(producer):
    """商品を作る。既定は producer の公開中の商品。owner と各カラムを引数で変えられる"""

    def make(owner=None, **kwargs):
        values = {"name": "ほうれん草", "price": 200, "stock": 10, "is_published": True}
        values.update(kwargs)
        product = Product(producer=owner or producer, **values)
        db.session.add(product)
        db.session.commit()
        return product

    return make


@pytest.fixture
def login(client):
    def do_login(user):
        return client.post("/login", data={"email": user.email, "password": "password"})

    return do_login

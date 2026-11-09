from flask import Blueprint, abort, render_template
from flask_login import current_user

from marche.extensions import db
from marche.forms import CartAddForm
from marche.models import Product
from marche.services.inventory import MAX_QUANTITY, available_stock

bp = Blueprint("shop", __name__)


def can_view(product: Product) -> bool:
    """公開中なら誰でも。非公開は出品した生産者と管理者だけ"""
    if product.is_published:
        return True
    if not current_user.is_authenticated:
        return False
    return current_user.is_admin or product.producer_id == current_user.id


@bp.route("/")
def index():
    products = db.session.scalars(
        db.select(Product)
        .filter_by(is_published=True)
        .order_by(Product.created_at.desc(), Product.id.desc())
    ).all()
    stocks = {p.id: available_stock(p) for p in products}
    return render_template("shop/index.html", products=products, stocks=stocks)


@bp.route("/products/<int:product_id>")
def detail(product_id: int):
    product = db.get_or_404(Product, product_id)
    if not can_view(product):
        abort(404)  # 非公開の商品は「ある」ことも教えない
    available = available_stock(product)
    return render_template(
        "shop/detail.html",
        product=product,
        available=available,
        max_quantity=min(MAX_QUANTITY, available),
        form=CartAddForm(),
    )

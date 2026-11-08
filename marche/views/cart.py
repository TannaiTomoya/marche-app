from flask import Blueprint, abort, flash, redirect, render_template, session, url_for

from marche.extensions import db
from marche.forms import CartAddForm, CartUpdateForm
from marche.models import Product
from marche.services.inventory import MAX_QUANTITY, available_stock

bp = Blueprint("cart", __name__, url_prefix="/cart")


def get_cart() -> dict[int, int]:
    """セッションのカート {"商品ID": 数量} を {商品ID: 数量} にして返す"""
    raw = session.get("cart", {})
    return {int(k): int(v) for k, v in raw.items()}


def save_cart(cart: dict[int, int]) -> None:
    session["cart"] = {str(k): v for k, v in cart.items() if v > 0}


def clear_cart() -> None:
    session.pop("cart", None)


@bp.route("/")
def index():
    cart = get_cart()
    lines = []
    for product_id, quantity in cart.items():
        product = db.session.get(Product, product_id)
        if product is None or not product.is_published:
            continue  # 非公開になった商品は表示から外す
        # 金額は表示のためだけに計算する。注文を作るときは DB の価格で計算し直す
        lines.append(
            {
                "product": product,
                "quantity": quantity,
                "subtotal": product.price * quantity,
            }
        )
    visible_ids = {line["product"].id for line in lines}
    if visible_ids != set(cart):
        save_cart({k: v for k, v in cart.items() if k in visible_ids})
    total = sum(line["subtotal"] for line in lines)
    return render_template(
        "cart/index.html",
        lines=lines,
        total=total,
        max_quantity=MAX_QUANTITY,
        form=CartUpdateForm(),
    )


@bp.route("/add/<int:product_id>", methods=["POST"])
def add(product_id: int):
    product = db.get_or_404(Product, product_id)
    if not product.is_published:
        abort(404)
    form = CartAddForm()
    if not form.validate_on_submit():
        flash("数量は1〜10にしてください")
        return redirect(url_for("shop.detail", product_id=product.id))
    cart = get_cart()
    quantity = cart.get(product.id, 0) + form.quantity.data
    if quantity > MAX_QUANTITY:
        flash(f"1つの商品は{MAX_QUANTITY}個まで買えます")
        return redirect(url_for("shop.detail", product_id=product.id))
    if quantity > available_stock(product):
        flash("在庫が足りません")
        return redirect(url_for("shop.detail", product_id=product.id))
    cart[product.id] = quantity
    save_cart(cart)
    flash(f"「{product.name}」をカートに入れました")
    return redirect(url_for("cart.index"))


@bp.route("/update/<int:product_id>", methods=["POST"])
def update(product_id: int):
    cart = get_cart()
    if product_id not in cart:
        abort(404)
    form = CartUpdateForm()
    if not form.validate_on_submit():
        flash("数量は0〜10にしてください")
        return redirect(url_for("cart.index"))
    quantity = form.quantity.data
    if quantity == 0:
        cart.pop(product_id)
        flash("カートから外しました")
    else:
        product = db.session.get(Product, product_id)
        if product is None or quantity > available_stock(product):
            flash("在庫が足りません")
            return redirect(url_for("cart.index"))
        cart[product_id] = quantity
        flash("数量を変えました")
    save_cart(cart)
    return redirect(url_for("cart.index"))

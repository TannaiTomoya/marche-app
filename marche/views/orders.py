from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from marche.extensions import db
from marche.models import Order
from marche.services.inventory import OrderError, create_order
from marche.views.cart import clear_cart, get_cart

bp = Blueprint("orders", __name__, url_prefix="/orders")


def get_own_order_or_403(order_id: int) -> Order:
    """注文を取得し、注文した本人か管理者でなければ 403 にする"""
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return order


@bp.route("/", methods=["POST"])
@login_required
def create():
    try:
        # 金額はフォームから受け取らない。カートの商品 ID と数量だけを使う
        order = create_order(current_user, get_cart())
    except OrderError as e:
        flash(str(e))
        return redirect(url_for("cart.index"))
    clear_cart()
    # 平日課題で、ここから Stripe Checkout へ移動する処理を足す
    flash("注文を作りました（支払い待ち）")
    return redirect(url_for("orders.detail", order_id=order.id))


@bp.route("/<int:order_id>")
@login_required
def detail(order_id: int):
    order = get_own_order_or_403(order_id)
    return render_template("orders/detail.html", order=order)

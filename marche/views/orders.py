from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from marche.extensions import db
from marche.models import Order, OrderStatus
from marche.services import inventory
from marche.services.inventory import OrderError, create_order
from marche.services.payment import PaymentError
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
    try:
        session_id, checkout_url = current_app.extensions[
            "payment"
        ].create_checkout_session(order)
    except PaymentError as e:
        inventory.cancel(order)
        flash(str(e))
        return redirect(url_for("cart.index"))
    order.stripe_checkout_session_id = session_id
    db.session.commit()
    clear_cart()
    return redirect(checkout_url, code=303)


@bp.route("/<int:order_id>")
@login_required
def detail(order_id: int):
    order = get_own_order_or_403(order_id)
    return render_template("orders/detail.html", order=order)


@bp.route("/<int:order_id>/complete")
@login_required
def complete(order_id: int):
    order = get_own_order_or_403(order_id)
    # 07章では表示だけ。URLに戻ったことを根拠に支払い済みにはしない。
    return render_template("orders/complete.html", order=order)


@bp.route("/<int:order_id>/cancel", methods=["GET", "POST"])
@login_required
def cancel(order_id: int):
    order = get_own_order_or_403(order_id)
    if request.method == "POST":
        if order.status == OrderStatus.PENDING and order.stripe_checkout_session_id:
            try:
                current_app.extensions["payment"].expire_session(
                    order.stripe_checkout_session_id
                )
            except PaymentError as e:
                flash(str(e))
                return redirect(url_for("orders.detail", order_id=order.id))
        if inventory.cancel(order):
            flash("注文を取り消しました")
        return redirect(url_for("orders.detail", order_id=order.id))
    return render_template("orders/cancel.html", order=order)

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
from marche.services.inventory import (
    OrderError,
    cancel_order,
    create_order,
    mark_as_paid,
)
from marche.services.payment import PaymentError
from marche.views.cart import clear_cart, get_cart

bp = Blueprint("orders", __name__, url_prefix="/orders")


def get_own_order_or_403(order_id: int) -> Order:
    """注文を取得し、注文した本人か管理者でなければ 403 にする"""
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return order


@bp.route("/", methods=["GET"])
@login_required
def index():
    orders = db.session.scalars(
        db.select(Order)
        .filter_by(user_id=current_user.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    return render_template("orders/index.html", orders=orders)


@bp.route("/", methods=["POST"])
@login_required
def create():
    try:
        # 金額はフォームから受け取らない。カートの商品 ID と数量だけを使う
        order = create_order(current_user, get_cart())
    except OrderError as e:
        flash(str(e))
        return redirect(url_for("cart.index"))

    payment = current_app.extensions["payment"]
    try:
        session_id, checkout_url = payment.create_checkout_session(order)
    except PaymentError as e:
        # 決済ページを作れなければ注文を取り消し、カートは残す
        cancel_order(order)
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
    session_id = request.args.get("session_id", "")
    # Webhook より先に戻ってきたときは、Stripe に問い合わせて確定する
    if (
        order.status == OrderStatus.PENDING
        and session_id
        and session_id == order.stripe_checkout_session_id
    ):
        payment = current_app.extensions["payment"]
        try:
            session = payment.retrieve_session(session_id)
        except PaymentError:
            session = None
        if session is not None and session.payment_status == "paid":
            mark_as_paid(order, session.payment_intent)
    return render_template("orders/complete.html", order=order)


@bp.route("/<int:order_id>/cancel", methods=["GET", "POST"])
@login_required
def cancel(order_id: int):
    order = get_own_order_or_403(order_id)
    if request.method == "GET":
        return render_template("orders/cancel.html", order=order)

    if order.status != OrderStatus.PENDING:
        flash("この注文は取り消せません")
        return redirect(url_for("orders.detail", order_id=order.id))
    if order.stripe_checkout_session_id:
        payment = current_app.extensions["payment"]
        try:
            # 先に決済ページを期限切れにする（取り消した後に支払われないように）
            payment.expire_session(order.stripe_checkout_session_id)
        except PaymentError:
            # 既に支払いが済んでいるなど。取り消さずに注文詳細へ
            flash("支払いが済んでいる可能性があるため、取り消せませんでした")
            return redirect(url_for("orders.detail", order_id=order.id))
    cancel_order(order)
    flash("注文を取り消しました")
    return redirect(url_for("orders.detail", order_id=order.id))

from flask import Blueprint, render_template, request

from marche.decorators import role_required
from marche.extensions import db
from marche.models import STATUS_LABELS, Order, OrderStatus, Role

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/orders")
@role_required(Role.ADMIN)
def orders():
    """全員の注文を新しい順に。?status=paid のように状態で絞り込める"""
    status = request.args.get("status", "")
    query = db.select(Order).order_by(Order.created_at.desc(), Order.id.desc())
    if status in {s.value for s in OrderStatus}:
        query = query.filter_by(status=status)
    else:
        status = ""
    return render_template(
        "admin/orders.html",
        orders=db.session.scalars(query).all(),
        status=status,
        status_labels=STATUS_LABELS,
    )

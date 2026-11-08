import logging
from datetime import timedelta

from sqlalchemy import case, func, update

from marche.extensions import db
from marche.models import Order, OrderItem, OrderStatus, Product, User, now_jst
from marche.services import mail

logger = logging.getLogger(__name__)

# 支払い待ちの注文が在庫を押さえる時間。Checkout Session の期限（31分）より少し長くする
HOLD_MINUTES = 35
MAX_QUANTITY = 10


class OrderError(Exception):
    """画面に出せる日本語のメッセージを持つ"""


def reserved_quantity(product_id: int) -> int:
    """作成から35分以内の支払い待ちの注文で押さえている数"""
    since = now_jst() - timedelta(minutes=HOLD_MINUTES)
    total = db.session.scalar(
        db.select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order)
        .where(
            OrderItem.product_id == product_id,
            Order.status == OrderStatus.PENDING,
            Order.created_at >= since,
        )
    )
    return int(total)


def available_stock(product: Product) -> int:
    """いま買える数 = stock − 押さえている数（0未満は0）"""
    return max(0, product.stock - reserved_quantity(product.id))


def create_order(user: User, cart: dict[int, int]) -> Order:
    """カートから支払い待ちの注文を作る。金額は DB の価格で計算する"""
    if not cart:
        raise OrderError("カートが空です")

    items = []
    for product_id, quantity in cart.items():
        product = db.session.get(Product, product_id)
        if product is None or not product.is_published:
            raise OrderError("購入できない商品がカートに入っています")
        if not 1 <= quantity <= MAX_QUANTITY:
            raise OrderError(
                f"「{product.name}」の数量は1〜{MAX_QUANTITY}にしてください"
            )
        available = available_stock(product)
        if quantity > available:
            raise OrderError(
                f"「{product.name}」の在庫が足りません（いま買える数: {available}）"
            )
        items.append(
            OrderItem(
                product_id=product.id,
                product_name=product.name,
                unit_price=product.price,
                quantity=quantity,
                subtotal=product.price * quantity,
            )
        )

    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING,
        total_amount=sum(item.subtotal for item in items),
        items=items,
    )
    db.session.add(order)
    db.session.commit()
    return order


def cancel_order(order: Order) -> bool:
    """支払い待ちのときだけ取り消しにする。取り消せたら True"""
    result = db.session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == OrderStatus.PENDING)
        .values(status=OrderStatus.CANCELLED)
    )
    db.session.commit()
    db.session.refresh(order)
    return result.rowcount == 1


def mark_as_paid(order: Order, payment_intent_id: str | None) -> bool:
    """支払いを確定する。Webhook と完了ページの両方から呼ぶ

    「pending のときだけ paid にする」を1つの UPDATE 文で行う。2回呼ばれても、
    確定（在庫を減らす・メールを送る）は1回だけになる。確定させたら True
    """
    result = db.session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == OrderStatus.PENDING)
        .values(
            status=OrderStatus.PAID,
            paid_at=now_jst(),
            stripe_payment_intent_id=payment_intent_id,
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        db.session.refresh(order)
        return False

    for item in order.items:
        product = db.session.get(Product, item.product_id)
        if product.stock < item.quantity:
            # 同時に最後の1個が売れた場合など。対策は拡張 E1
            logger.warning(
                "在庫が足りないまま支払いが確定しました order_id=%s product_id=%s",
                order.id,
                product.id,
            )
        # 読んでから書くと同時の確定で数がずれるので、SQL の中で減らす（0未満にはしない）
        db.session.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(
                stock=case(
                    (Product.stock >= item.quantity, Product.stock - item.quantity),
                    else_=0,
                )
            )
        )
    db.session.commit()
    db.session.refresh(order)

    try:
        mail.send_order_paid(order)
    except Exception:
        # メールが送れなくても、支払いの確定は取り消さない
        logger.exception("注文確認メールを送れませんでした order_id=%s", order.id)
    return True

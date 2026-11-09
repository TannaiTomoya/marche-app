from datetime import timedelta

from sqlalchemy import func

from marche.extensions import db
from marche.models import Order, OrderItem, OrderStatus, Product, User, now_jst

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

"""メールを送るのはこのファイルだけ。開発ではログに出すだけ（MAIL_BACKEND=log）"""

import logging
import smtplib
from email.message import EmailMessage

from flask import current_app, url_for

logger = logging.getLogger(__name__)


def build_order_paid_message(order) -> EmailMessage:
    lines = [
        f"{order.user.name} 様",
        "",
        "はちまん産直マルシェをご利用いただき、ありがとうございます。",
        "お支払いを確認しました。",
        "",
        f"注文番号: {order.id}",
        "",
    ]
    for item in order.items:
        lines.append(
            f"・{item.product_name}  {item.unit_price:,}円 × {item.quantity}"
            f" = {item.subtotal:,}円"
        )
    lines += [
        "",
        f"合計: {order.total_amount:,}円",
        "",
        "注文の詳細:",
        url_for("orders.detail", order_id=order.id, _external=True),
    ]

    message = EmailMessage()
    message["Subject"] = (
        f"【はちまん産直マルシェ】ご注文ありがとうございます（注文番号 {order.id}）"
    )
    message["From"] = current_app.config["MAIL_FROM"]
    message["To"] = order.user.email
    message.set_content("\n".join(lines))
    return message


def send(message: EmailMessage) -> None:
    app = current_app
    if app.testing:
        app.extensions.setdefault("mail_outbox", []).append(message)
        return
    if app.config["MAIL_BACKEND"] == "smtp":
        with smtplib.SMTP(
            app.config["MAIL_SERVER"], app.config["MAIL_PORT"], timeout=10
        ) as smtp:
            if app.config["MAIL_USE_TLS"]:
                smtp.starttls()
            if app.config["MAIL_USERNAME"]:
                smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
            smtp.send_message(message)
        logger.info("メールを送りました 件名=%s", message["Subject"])
        return
    # 開発用。送らずにターミナルに出す
    logger.info("メール（開発用。送信しない）\n%s", message)


def send_order_paid(order) -> None:
    send(build_order_paid_message(order))

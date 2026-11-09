from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user

from marche.decorators import role_required
from marche.extensions import db
from marche.forms import ProductForm
from marche.models import OrderItem, Product, Role
from marche.uploads import (
    InvalidImageError,
    delete_image,
    detect_media_type,
    save_image,
)

bp = Blueprint("producer", __name__, url_prefix="/producer")


def get_own_product_or_403(product_id: int) -> Product:
    """自分の商品だけを返す。他の生産者の商品なら 403"""
    product = db.get_or_404(Product, product_id)
    if product.producer_id != current_user.id:
        abort(403)
    return product


def save_uploaded_image(form: ProductForm) -> str | None:
    """写真が選ばれていれば中身を確かめて保存し、ファイル名を返す

    選ばれていなければ None。画像でなければフォームにエラーを付けて InvalidImageError
    """
    file = form.image.data
    if not file or not file.filename:
        return None
    data = file.read()
    media_type = detect_media_type(data)
    if media_type is None:
        form.image.errors.append("画像として読み込めないファイルです")
        raise InvalidImageError
    return save_image(data, media_type)


def commit_or_delete_image(filename: str | None) -> None:
    """保存に失敗したら、先に保存した写真を消してから例外を投げ直す（孤児ファイルを残さない）"""
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        delete_image(filename)
        raise


def render_form(form: ProductForm, product: Product | None, status: int = 200):
    return render_template("producer/form.html", form=form, product=product), status


@bp.route("/products")
@role_required(Role.PRODUCER)
def index():
    products = db.session.scalars(
        db.select(Product)
        .filter_by(producer_id=current_user.id)
        .order_by(Product.created_at.desc(), Product.id.desc())
    ).all()
    return render_template("producer/index.html", products=products)


@bp.route("/products/new", methods=["GET", "POST"])
@role_required(Role.PRODUCER)
def new():
    form = ProductForm()
    if form.validate_on_submit():
        try:
            filename = save_uploaded_image(form)
        except InvalidImageError:
            return render_form(form, None, 422)
        product = Product(
            # 出品者はログイン中のユーザー。フォームからは受け取らない
            producer_id=current_user.id,
            name=form.name.data.strip(),
            price=form.price.data,
            stock=form.stock.data,
            description=(form.description.data or "").strip(),
            is_published=form.is_published.data,
            image_filename=filename,
        )
        db.session.add(product)
        commit_or_delete_image(filename)
        flash("商品を登録しました")
        return redirect(url_for("producer.index"))
    return render_form(form, None, 422 if form.is_submitted() else 200)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@role_required(Role.PRODUCER)
def edit(product_id: int):
    product = get_own_product_or_403(product_id)
    form = ProductForm(obj=product)
    if form.validate_on_submit():
        try:
            filename = save_uploaded_image(form)
        except InvalidImageError:
            return render_form(form, product, 422)
        old_filename = product.image_filename
        product.name = form.name.data.strip()
        product.price = form.price.data
        product.stock = form.stock.data
        product.description = (form.description.data or "").strip()
        product.is_published = form.is_published.data
        if filename:
            product.image_filename = filename
        commit_or_delete_image(filename)
        if filename:
            delete_image(old_filename)  # 差し替えたら古い写真を消す
        flash("商品を更新しました")
        return redirect(url_for("producer.index"))
    return render_form(form, product, 422 if form.is_submitted() else 200)


@bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@role_required(Role.PRODUCER)
def toggle(product_id: int):
    product = get_own_product_or_403(product_id)
    product.is_published = not product.is_published
    db.session.commit()
    flash("公開しました" if product.is_published else "非公開にしました")
    return redirect(url_for("producer.index"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@role_required(Role.PRODUCER)
def delete(product_id: int):
    product = get_own_product_or_403(product_id)
    # SQLite は設定しないと外部キーの restrict を確かめないので、ここでも確かめる
    has_orders = db.session.scalar(
        db.select(OrderItem.id).filter_by(product_id=product.id).limit(1)
    )
    if has_orders:
        flash("注文がある商品は削除できません。非公開にしてください")
        return redirect(url_for("producer.index"))
    filename = product.image_filename
    db.session.delete(product)
    db.session.commit()
    delete_image(filename)  # 商品を消したら写真も消す
    flash("商品を削除しました")
    return redirect(url_for("producer.index"))

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user

from marche.decorators import role_required
from marche.extensions import db
from marche.forms import ProductForm
from marche.models import OrderItem, Product, Role
from marche.services.uploads import UploadError, delete_image, save_image

bp = Blueprint("producer", __name__, url_prefix="/producer")


def get_own_product_or_403(product_id: int) -> Product:
    """商品を取得し、自分の商品でなければ 403 にする"""
    product = db.get_or_404(Product, product_id)
    if product.producer_id != current_user.id:
        abort(403)
    return product


def _save_uploaded_image(form: ProductForm) -> str | None:
    """写真が選ばれていれば保存してファイル名を返す。不正なら form にエラーを付ける"""
    file = form.image.data
    if not file or not file.filename:
        return None
    try:
        return save_image(file)
    except UploadError as e:
        form.image.errors.append(str(e))
        raise


@bp.route("/products")
@role_required(Role.PRODUCER)
def products():
    items = db.session.scalars(
        db.select(Product)
        .filter_by(producer_id=current_user.id)
        .order_by(Product.created_at.desc(), Product.id.desc())
    ).all()
    return render_template("producer/products.html", products=items)


@bp.route("/products/new", methods=["GET", "POST"])
@role_required(Role.PRODUCER)
def new_product():
    form = ProductForm()
    if form.validate_on_submit():
        try:
            filename = _save_uploaded_image(form)
        except UploadError:
            return render_template(
                "producer/product_form.html", form=form, product=None
            ), 422
        product = Product(
            producer_id=current_user.id,
            name=form.name.data.strip(),
            price=form.price.data,
            stock=form.stock.data,
            description=(form.description.data or "").strip(),
            is_published=form.is_published.data,
            image_filename=filename,
        )
        db.session.add(product)
        db.session.commit()
        flash("商品を登録しました")
        return redirect(url_for("producer.products"))
    status = 422 if form.is_submitted() else 200
    return render_template(
        "producer/product_form.html", form=form, product=None
    ), status


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@role_required(Role.PRODUCER)
def edit_product(product_id: int):
    product = get_own_product_or_403(product_id)
    form = ProductForm(obj=product)
    if form.validate_on_submit():
        try:
            filename = _save_uploaded_image(form)
        except UploadError:
            return render_template(
                "producer/product_form.html", form=form, product=product
            ), 422
        old_filename = product.image_filename
        product.name = form.name.data.strip()
        product.price = form.price.data
        product.stock = form.stock.data
        product.description = (form.description.data or "").strip()
        product.is_published = form.is_published.data
        if filename:
            product.image_filename = filename
        db.session.commit()
        if filename:
            delete_image(old_filename)
        flash("商品を更新しました")
        return redirect(url_for("producer.products"))
    status = 422 if form.is_submitted() else 200
    return render_template(
        "producer/product_form.html", form=form, product=product
    ), status


@bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@role_required(Role.PRODUCER)
def toggle_product(product_id: int):
    product = get_own_product_or_403(product_id)
    product.is_published = not product.is_published
    db.session.commit()
    flash("公開しました" if product.is_published else "非公開にしました")
    return redirect(url_for("producer.products"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@role_required(Role.PRODUCER)
def delete_product(product_id: int):
    product = get_own_product_or_403(product_id)
    # SQLite は設定しないと外部キーの restrict を確かめないので、ここでも確かめる
    has_orders = db.session.scalar(
        db.select(OrderItem.id).filter_by(product_id=product.id).limit(1)
    )
    if has_orders:
        flash("注文がある商品は削除できません。非公開にしてください")
        return redirect(url_for("producer.products"))
    filename = product.image_filename
    db.session.delete(product)
    db.session.commit()
    delete_image(filename)
    flash("商品を削除しました")
    return redirect(url_for("producer.products"))

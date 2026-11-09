from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileSize
from wtforms import (
    BooleanField,
    EmailField,
    IntegerField,
    PasswordField,
    RadioField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Regexp

from marche.models import Role

# 写真の上限。Claude API が受け取れる画像の上限（5MB）とも同じ
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# email-validator パッケージを足さずに済むよう、形だけを正規表現で確かめる
EMAIL = Regexp(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$", message="メールアドレスの形式で入力してください"
)


class RegisterForm(FlaskForm):
    name = StringField("名前", validators=[DataRequired(), Length(max=50)])
    email = EmailField(
        "メールアドレス", validators=[DataRequired(), EMAIL, Length(max=255)]
    )
    password = PasswordField("パスワード", validators=[DataRequired(), Length(min=8)])
    # 選択肢に admin を入れない。送られてきても RadioField の検証で弾かれる
    role = RadioField(
        "登録の種類",
        choices=[(Role.CUSTOMER, "購入者"), (Role.PRODUCER, "生産者")],
        default=Role.CUSTOMER,
    )


class LoginForm(FlaskForm):
    email = EmailField("メールアドレス", validators=[DataRequired(), EMAIL])
    password = PasswordField("パスワード", validators=[DataRequired()])


class ProductForm(FlaskForm):
    name = StringField("商品名", validators=[DataRequired(), Length(max=50)])
    price = IntegerField(
        "価格（円、税込み）",
        validators=[
            InputRequired(),
            NumberRange(50, 100_000, message="50〜100,000円にしてください"),
        ],
    )
    stock = IntegerField(
        "在庫数",
        validators=[
            InputRequired(),
            NumberRange(0, 999, message="0〜999にしてください"),
        ],
    )
    description = TextAreaField("紹介文", validators=[Length(max=2000)])
    # 拡張子と大きさはここで、中身はビューで detect_media_type() を使って確かめる
    image = FileField(
        "写真（JPEG / PNG / WebP、5MB まで）",
        validators=[
            FileAllowed(
                ["jpg", "jpeg", "png", "webp"],
                message="JPEG / PNG / WebP の画像を選んでください",
            ),
            FileSize(
                max_size=MAX_IMAGE_BYTES, message="5MB 以下の画像を選んでください"
            ),
        ],
    )
    is_published = BooleanField("公開する")


class CartAddForm(FlaskForm):
    quantity = IntegerField(
        "数量",
        default=1,
        validators=[InputRequired(), NumberRange(1, 10, message="1〜10にしてください")],
    )


class CartUpdateForm(FlaskForm):
    quantity = IntegerField(
        "数量",
        validators=[InputRequired(), NumberRange(0, 10, message="0〜10にしてください")],
    )

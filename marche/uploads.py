"""商品の写真の保存。拡張子は信用せず、中身（先頭のバイト）で種類を判定する"""

import uuid
from pathlib import Path

from flask import current_app

# 保存する拡張子は、中身から判定した種類で決める
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class InvalidImageError(Exception):
    """送られたファイルが JPEG / PNG / WebP の画像ではない"""


def detect_media_type(data: bytes) -> str | None:
    """先頭のバイト列（マジックナンバー）で画像の種類を判定する。画像でなければ None"""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def save_image(data: bytes, media_type: str) -> str:
    """ランダムなファイル名で保存し、ファイル名を返す。元のファイル名は使わない"""
    filename = f"{uuid.uuid4().hex}.{EXTENSIONS[media_type]}"
    folder = Path(current_app.config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_bytes(data)
    return filename


def delete_image(filename: str | None) -> None:
    """写真を消す。無くてもエラーにしない"""
    if not filename:
        return
    (Path(current_app.config["UPLOAD_FOLDER"]) / filename).unlink(missing_ok=True)

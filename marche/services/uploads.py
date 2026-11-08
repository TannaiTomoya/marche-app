import os
import uuid

from flask import current_app

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


class UploadError(Exception):
    """画面に出せる日本語のメッセージを持つ"""


def _detect_extension(data: bytes) -> str | None:
    """ファイルの先頭のバイトから、本当の形式を調べる"""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_image(file_storage) -> str:
    """写真を確かめて保存し、サーバーで付け直したファイル名を返す"""
    original = file_storage.filename or ""
    extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadError("写真は JPEG / PNG / WebP にしてください")

    data = file_storage.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise UploadError("写真は 5MB 以下にしてください")
    detected = _detect_extension(data)
    if detected is None:
        raise UploadError("写真のファイルとして読み込めませんでした")

    # 元のファイル名は使わない（パスの細工や上書きを防ぐ）
    filename = f"{uuid.uuid4().hex}.{detected}"
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, filename), "wb") as f:
        f.write(data)
    return filename


def delete_image(filename: str | None) -> None:
    if not filename:
        return
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    if os.path.exists(path):
        os.remove(path)

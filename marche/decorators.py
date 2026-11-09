from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def role_required(role):
    """ログインしていなければログイン画面へ、ロールが違えば 403 にする"""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role != role:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator

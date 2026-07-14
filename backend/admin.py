"""
Admin authentication and permission system
For now, this uses a simple session-based system with the user's Google account email.
In production, this should be replaced with OAuth2 / Google Sign-In.
"""
from functools import wraps
from flask import request, jsonify
from config import ADMINS_FILE, load_json, save_json

DEFAULT_ADMIN_EMAIL = "hiko@lastarroad.com"


def init_admins():
    """Initialize the admin list with the first admin if empty"""
    admins = load_json(ADMINS_FILE, [])
    if not admins:
        admins = [DEFAULT_ADMIN_EMAIL]
        save_json(ADMINS_FILE, admins)
    return admins


def get_admins():
    """Return list of admin emails"""
    return load_json(ADMINS_FILE, [])


def add_admin(email):
    """Add a new admin email"""
    admins = get_admins()
    email = email.strip().lower()
    if email and email not in admins:
        admins.append(email)
        save_json(ADMINS_FILE, admins)
        return True
    return False


def remove_admin(email):
    """Remove an admin email (cannot remove the last admin)"""
    admins = get_admins()
    email = email.strip().lower()
    if email in admins and len(admins) > 1:
        admins.remove(email)
        save_json(ADMINS_FILE, admins)
        return True
    return False


def is_admin(email):
    """Check if email is in admin list"""
    if not email:
        return False
    return email.strip().lower() in [a.lower() for a in get_admins()]


def require_admin(f):
    """Decorator: require admin email in request header"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        email = request.headers.get('X-Admin-Email', request.headers.get('x-admin-email', ''))
        if not email or not is_admin(email):
            return jsonify({"error": "Forbidden: admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

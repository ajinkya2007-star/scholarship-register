import io
import os
import secrets
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, session, send_file, send_from_directory, redirect, render_template_string
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from openpyxl import Workbook
from werkzeug.security import generate_password_hash, check_password_hash

BASE = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///scholarship_local.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
app.config.update(
    SQLALCHEMY_DATABASE_URI=DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=200_000,
)

db = SQLAlchemy(app)
limiter = Limiter(get_remote_address, app=app, default_limits=[])

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    phone = db.Column(db.String(10), unique=True, nullable=False, index=True)
    address = db.Column(db.Text, nullable=False)
    permanent_address = db.Column(db.Text, nullable=False)
    linkedin = db.Column(db.String(500), nullable=True)
    certificate_name = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(512), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def normalize_phone(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())[-10:]


def clean(value, max_len=2000):
    value = str(value or "").strip()
    return value[:max_len]


def valid_phone(phone):
    return len(phone) == 10 and phone.isdigit()


def public_user(user):
    return {
        "id": user.id,
        "name": user.name,
        "age": user.age,
        "phone": user.phone,
        "address": user.address,
        "homeAddress": user.permanent_address,
        "linkedin": user.linkedin or "",
        "certificateName": user.certificate_name or "",
        "signedUpAt": user.created_at.isoformat() if user.created_at else None,
    }


def same_origin():
    # Same-origin browser requests are expected. Allow requests without Origin
    # for command-line/API health checks, but reject cross-site browser posts.
    origin = request.headers.get("Origin")
    if not origin:
        return True
    host = request.host_url.rstrip("/")
    return origin.rstrip("/") == host


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_ok"):
            return redirect("/admin/login")
        return fn(*args, **kwargs)
    return wrapper


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.path.startswith("/api/") or request.path.startswith("/admin"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
@app.get("/index.html")
def index():
    return send_from_directory(BASE, "index.html", max_age=0)


@app.get("/api/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify(success=True, database=True)
    except Exception:
        return jsonify(success=False, database=False), 503


@app.get("/api/me")
def me():
    uid = session.get("user_id")
    if not uid:
        return jsonify(authenticated=False)
    user = db.session.get(User, uid)
    if not user:
        session.clear()
        return jsonify(authenticated=False)
    return jsonify(authenticated=True, user=public_user(user))


@app.post("/api/register")
@limiter.limit("8 per hour")
def register():
    if not same_origin():
        return jsonify(success=False, message="Invalid request origin."), 403
    data = request.get_json(silent=True) or {}
    name = clean(data.get("name"), 200)
    phone = normalize_phone(data.get("phone"))
    address = clean(data.get("address"), 2000)
    home = clean(data.get("homeAddress"), 2000)
    linkedin = clean(data.get("linkedin"), 500)
    certificate = clean(data.get("certificateName"), 255)
    password = str(data.get("password") or "")
    try:
        age = int(data.get("age"))
    except (TypeError, ValueError):
        age = 0

    if not name or not valid_phone(phone) or not address or not home:
        return jsonify(success=False, message="Please complete all required fields."), 400
    if not (1 <= age <= 100):
        return jsonify(success=False, message="Please enter a valid age."), 400
    if len(password) < 6 or not any(ch.isdigit() for ch in password) or not any(ch in "!@#$%^&*()_-+=:;\"'<>,.?/\\|`~[]{}" for ch in password):
        return jsonify(success=False, message="Password needs at least 6 characters, including a number and a special character."), 400
    if len(password) > 200:
        return jsonify(success=False, message="Password is too long."), 400

    if User.query.filter_by(phone=phone).first():
        return jsonify(success=False, message="This mobile number is already registered. Please log in."), 409

    user = User(
        name=name,
        age=age,
        phone=phone,
        address=address,
        permanent_address=home,
        linkedin=linkedin,
        certificate_name=certificate,
        password_hash=generate_password_hash(password, method="scrypt"),
    )
    db.session.add(user)
    db.session.commit()
    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    return jsonify(success=True, message="Registration saved securely.", user=public_user(user)), 201


@app.post("/api/login")
@limiter.limit("10 per minute")
def login():
    if not same_origin():
        return jsonify(success=False, message="Invalid request origin."), 403
    data = request.get_json(silent=True) or {}
    phone = normalize_phone(data.get("phone"))
    password = str(data.get("password") or "")
    if not valid_phone(phone) or not password:
        return jsonify(success=False, message="Enter your mobile number and password."), 400
    user = User.query.filter_by(phone=phone).first()
    if not user or not check_password_hash(user.password_hash, password):
        # Same response for both cases to avoid account enumeration.
        return jsonify(success=False, message="Invalid mobile number or password."), 401
    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    return jsonify(success=True, user=public_user(user))


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(success=True)


ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

ADMIN_LOGIN_HTML = """
<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Private Admin Login</title>
<style>body{font-family:system-ui;background:#f3efe4;display:grid;place-items:center;min-height:100vh;margin:0}.card{width:min(420px,90vw);background:white;padding:32px;border-radius:18px;box-shadow:0 20px 60px #0002}input{width:100%;box-sizing:border-box;padding:12px;margin:7px 0 14px;border:1px solid #ccc;border-radius:9px}button{width:100%;padding:12px;border:0;border-radius:9px;background:#172b78;color:white;font-weight:700}.err{color:#a00;margin-bottom:12px}</style></head>
<body><form class=card method=post><h1>Private Admin</h1><p>Registration database access.</p>{% if error %}<div class=err>{{error}}</div>{% endif %}<label>Username</label><input name=username autocomplete=username required><label>Password</label><input name=password type=password autocomplete=current-password required><button>Sign in</button></form></body></html>
"""

ADMIN_HTML = """
<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Private Registration Admin</title>
<style>body{font-family:system-ui;margin:0;background:#f3efe4;color:#172b78}.wrap{max-width:1200px;margin:30px auto;padding:0 18px}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.btn{display:inline-block;padding:10px 14px;border-radius:9px;background:#172b78;color:white;text-decoration:none;border:0}.danger{background:#7c2330}table{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}th,td{padding:10px;border-bottom:1px solid #eee;text-align:left;font-size:13px;vertical-align:top}th{background:#faf8f2}.table-wrap{overflow:auto;margin-top:20px}.stat{background:white;padding:16px;border-radius:14px;margin-top:15px}.muted{color:#6d6654}</style></head><body><div class=wrap><div class=top><div><h1>Private Registration Database</h1><div class=muted>{{count}} registrations</div></div><div><a class=btn href=/admin/export.xlsx>Export Excel</a> <a class='btn danger' href=/admin/logout>Logout</a></div></div><div class=table-wrap><table><thead><tr><th>Date</th><th>Name</th><th>Age</th><th>Mobile</th><th>Residential Address</th><th>Permanent Address</th><th>LinkedIn</th><th>Certificate</th></tr></thead><tbody>{% for u in users %}<tr><td>{{u.created_at}}</td><td>{{u.name}}</td><td>{{u.age}}</td><td>{{u.phone}}</td><td>{{u.address}}</td><td>{{u.permanent_address}}</td><td>{{u.linkedin or ''}}</td><td>{{u.certificate_name or ''}}</td></tr>{% endfor %}</tbody></table></div></div></body></html>
"""

@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def admin_login():
    if request.method == "POST":
        if not ADMIN_USERNAME or not ADMIN_PASSWORD:
            return render_template_string(ADMIN_LOGIN_HTML, error="Admin credentials are not configured on the server."), 503
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session["admin_ok"] = True
            return redirect("/admin")
        time.sleep(0.4)
        return render_template_string(ADMIN_LOGIN_HTML, error="Invalid credentials."), 401
    return render_template_string(ADMIN_LOGIN_HTML, error=None)


@app.get("/admin")
@login_required
def admin():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template_string(ADMIN_HTML, users=users, count=len(users))


@app.get("/admin/export.xlsx")
@login_required
def admin_export():
    wb = Workbook()
    ws = wb.active
    ws.title = "Registrations"
    ws.append(["Signed up at", "Name", "Age", "Phone", "Address", "Permanent address", "LinkedIn", "Certificate file name"])
    for u in User.query.order_by(User.created_at.asc()).all():
        ws.append([u.created_at.isoformat(), u.name, u.age, u.phone, u.address, u.permanent_address, u.linkedin or "", u.certificate_name or ""])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="registrations.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")


@app.errorhandler(429)
def too_many(e):
    return jsonify(success=False, message="Too many attempts. Please wait a little and try again."), 429


@app.errorhandler(413)
def too_large(e):
    return jsonify(success=False, message="Request is too large."), 413


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # Local development only. Production uses Gunicorn.
    app.run(host="0.0.0.0", port=port, debug=False)

# Scholarship Register — 24/7 private registration

This version replaces browser-only account storage and the local Excel live database with a server-side database suitable for a public multi-user deployment.

## Security model
- User passwords are hashed on the server with Werkzeug's scrypt password hashing.
- Passwords are never written to Excel or returned by the API.
- Sessions use an HttpOnly, SameSite cookie. Production sets Secure cookies.
- Registration and login endpoints are rate-limited.
- Cross-origin browser POSTs are rejected.
- The database is never exposed to visitors.
- The admin area is separate from the public website and requires server environment credentials.
- Admin can export registrations to Excel on demand.
- The old `registrations.xlsx` is treated as an archive, not as the live multi-user database.

## Local test on Mac

```bash
cd scholarship-private-public
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="replace-with-a-long-random-secret"
export COOKIE_SECURE="false"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="choose-a-strong-admin-password"
python3 app.py
```

Open `http://127.0.0.1:8000/`.
Admin: `http://127.0.0.1:8000/admin/login`

## Public 24/7 deployment on Render

1. Put this folder in a private GitHub repository.
2. In Render, create the Blueprint from `render.yaml`, or create a Web Service and a PostgreSQL database. The included Blueprint uses paid, always-on compute plans; Render Free web services can spin down after 15 minutes of inactivity and Free Postgres expires after 30 days.
3. Set `ADMIN_USERNAME` and a long random `ADMIN_PASSWORD` in Render Environment Variables.
4. Deploy with build command `pip install -r requirements.txt` and start command `gunicorn app:app`.
5. Use the public HTTPS URL Render gives you.

Do NOT put `ADMIN_PASSWORD`, `DATABASE_URL`, or other secrets in the HTML or Git repository.

## Existing Excel

The supplied `registrations.xlsx` is included as a private archive/reference. New public registrations go to PostgreSQL. Use `/admin/export.xlsx` to create a fresh private Excel export whenever needed.

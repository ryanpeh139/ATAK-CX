#!/usr/bin/env python3
"""ATAK-CX Manager: a web dashboard for the things takcx does.

Served by nginx at https://<server>/manage/ and runs with OpenTAKServer's Python
(which has Flask) on 127.0.0.1 only. Log in with any OpenTAKServer administrator
account; two-factor codes are supported.

Everything that changes the server runs the same `takcx` commands you'd type,
as background jobs whose output you can watch. Things that need full root
(installing add-ons) are shown as a command to run over SSH instead; the manager
can only restart a short, fixed list of services (see setup/enable-manager.sh).
"""

import collections
import datetime
import email.utils
import glob
import hashlib
import html
import http.client
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid

from flask import (Blueprint, Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from markupsafe import Markup

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO_DIR, "takcx"))
import takcx as T  # noqa: E402
import ots_update as U  # noqa: E402
import brand as B  # noqa: E402

PORT = int(os.environ.get("TAKCX_MANAGER_PORT", "8096"))
TAKCX_PY = os.path.join(REPO_DIR, "takcx", "takcx.py")
OTS_PY = T.OTS_PYTHON if os.path.exists(T.OTS_PYTHON) else sys.executable
BACKUP_DIR = os.path.expanduser(os.environ.get("TAKCX_BACKUP_DIR", "~/takcx-backups"))
UPLOAD_DIR = os.path.join(T.TAKCX_HOME, "uploads")
INSECURE_COOKIES = os.environ.get("TAKCX_MANAGER_INSECURE_COOKIES") == "1"  # tests only

bp = Blueprint("m", __name__, url_prefix="/manage")


# --------------------------------------------------------------------------- app setup

def secret_key():
    path = os.path.join(T.TAKCX_HOME, "manager.key")
    if not os.path.exists(path):
        os.makedirs(T.TAKCX_HOME, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return open(path).read().strip()


def create_app():
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
    app.config.update(
        SECRET_KEY=secret_key(),
        SESSION_COOKIE_NAME="takcx_manager",
        SESSION_COOKIE_PATH="/manage",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=not INSECURE_COOKIES,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=12),
        MAX_CONTENT_LENGTH=300 * 1024 * 1024,
    )
    app.register_blueprint(bp)

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if request.path.startswith("/manage") and not request.path.endswith("/download"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app


# --------------------------------------------------------------------------- auth

_failures = collections.defaultdict(list)  # ip -> [timestamps]
LOCKOUT_TRIES, LOCKOUT_SECONDS = 5, 300


def client_ip():
    # nginx sets X-Real-IP; only trust it when the request came through nginx.
    if request.remote_addr in ("127.0.0.1", "::1") and request.headers.get("X-Real-IP"):
        return request.headers["X-Real-IP"]
    return request.remote_addr or "?"


def locked_out(ip):
    now = time.time()
    _failures[ip] = [t for t in _failures[ip] if now - t < LOCKOUT_SECONDS]
    return len(_failures[ip]) >= LOCKOUT_TRIES


OTS_COOKIES = ("session", "remember_token", "XSRF-TOKEN")  # OpenTAKServer's login (path /)
DOWN = "down"


class OtsLogin:
    """Someone's OpenTAKServer login, checked through its API.

    The Manager and the web map share it: the cookies OpenTAKServer hands out when you log
    in here go to the browser (path /), so the web map is logged in too, and the Manager
    trusts a web map login the same way. Logging out of either ends both."""

    def __init__(self, cookies=None):
        self.api = T.OTS(T.load_team()["SERVER_ADDRESS"])
        self.api.cookies = dict(cookies or {})

    @classmethod
    def from_browser(cls):
        return cls({k: request.cookies[k] for k in OTS_COOKIES if request.cookies.get(k)})

    def login(self, username, password, remember=False):
        status, data = self.api.request("POST", "/api/login", {"username": username, "password": password,
                                                               "remember": bool(remember)})
        resp = data.get("response", {}) if isinstance(data, dict) else {}
        if status == 200 and resp.get("tf_required"):
            return "2fa"
        return "ok" if status == 200 else "bad"

    def two_factor(self, code):
        status, _ = self.api.request("POST", "/api/tf-validate", {"code": code})
        return status == 200

    def me(self):
        """The logged-in person ({username, is_admin, ...}), None if not logged in, or DOWN."""
        try:
            status, me = self.api.request("GET", "/api/me")
        except T.TakcxError:
            return DOWN
        if status >= 500:
            return DOWN
        if status != 200 or not isinstance(me, dict) or not me.get("username") or not me.get("active", True):
            return None
        me["is_admin"] = "administrator" in [r.get("name") for r in me.get("roles", [])]
        return me

    def logout(self):
        self.api.request("POST", "/api/logout")


def give_browser(resp, cookies):
    """Pass OpenTAKServer's login cookies on to the browser, for the whole site."""
    for name, value in cookies.items():
        if name in OTS_COOKIES:
            resp.set_cookie(name, value, path="/", secure=not INSECURE_COOKIES, samesite="Strict",
                            httponly=name != "XSRF-TOKEN",  # the web map's scripts read XSRF-TOKEN
                            max_age=365 * 86400 if name == "remember_token" else None)
    return resp


def clear_browser(resp):
    for name in OTS_COOKIES:
        resp.delete_cookie(name, path="/", secure=not INSECURE_COOKIES, samesite="Strict")
    return resp


_seen = collections.OrderedDict()  # hash of the browser's login cookies -> (checked at, me)


def browser_login():
    """Whose shared login this browser has, checked with OpenTAKServer at most every 30 s."""
    ots = OtsLogin.from_browser()
    if not (ots.api.cookies.get("session") or ots.api.cookies.get("remember_token")):
        return None
    key = hashlib.sha256(json.dumps(ots.api.cookies, sort_keys=True).encode()).hexdigest()
    hit = _seen.get(key)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    before = dict(ots.api.cookies)
    me = ots.me()
    if me == DOWN:
        return hit[1] if hit else DOWN
    renewed = {k: v for k, v in ots.api.cookies.items() if before.get(k) != v}
    if renewed:  # e.g. a new session made from "keep me logged in"
        g.ots_cookies = renewed
    _seen[key] = (time.time(), me)
    while len(_seen) > 500:
        _seen.popitem(last=False)
    return me


def safe_next(value):
    """Only ever send people on to a page of this site."""
    value = (value or "").strip()
    if not value.startswith("/") or value.startswith("//") or any(c in value for c in "\\\r\n"):
        return ""
    return value


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def start_session(username):
    session.clear()
    session.permanent = True
    session["user"] = username
    csrf_token()


PUBLIC = ("m.login", "m.two_factor", "m.change_password", "m.logout")


@bp.before_request
def require_login():
    if request.endpoint not in PUBLIC:
        me = browser_login()
        if me == DOWN:
            # OpenTAKServer itself is down: keep the Manager usable so it can be restarted.
            allowed = bool(session.get("user"))
        elif me and me["is_admin"]:
            if session.get("user") != me["username"]:
                start_session(me["username"])  # logged in on the web map: no second login
            allowed = True
        else:
            allowed = False
            if me:
                flash(f"You're logged in as {me['username']}, but the Manager is for server admins.", "warn")
        if not allowed:
            session.pop("user", None)
            nxt = request.full_path.rstrip("?") if request.method == "GET" else ""
            return redirect(url_for("m.login", next=nxt or None))
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Form expired. Go back, reload the page and try again.")


@bp.after_request
def renew_browser_login(resp):
    if g.get("ots_cookies"):
        give_browser(resp, g.ots_cookies)
    return resp


@bp.app_context_processor
def template_globals():
    team = T.read_shell_conf(os.path.join(T.TAKCX_HOME, "team.conf"))
    return {"csrf": csrf_token(), "user": session.get("user"), "team": team,
            "running_jobs": sum(1 for j in JOBS.values() if j["status"] == "running"),
            "restartable": RESTARTABLE, "service_labels": SERVICE_LABELS}


@bp.route("/login", methods=["GET", "POST"])
def login():
    nxt = safe_next(request.values.get("next"))
    if request.method == "GET":
        return render_template("login.html", next=nxt, bye=request.args.get("bye"))
    ip = client_ip()
    page = lambda code: (render_template("login.html", next=nxt), code)  # noqa: E731
    if locked_out(ip):
        flash("Too many failed logins. Wait 5 minutes and try again.", "bad")
        return page(429)
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    remember = bool(request.form.get("remember"))
    try:
        ots = OtsLogin()
        result = ots.login(username, password, remember)
    except T.TakcxError as e:
        flash(str(e), "bad")
        return page(503)
    if result == "bad":
        _failures[ip].append(time.time())
        flash("Wrong username or password.", "bad")
        return page(401)
    if result == "2fa":
        session.clear()
        session.update(pending_cookies=ots.api.cookies, pending_next=nxt)
        csrf_token()
        return redirect(url_for("m.two_factor"))
    return finish_login(ots, ip, nxt)


@bp.route("/login/code", methods=["GET", "POST"])
def two_factor():
    if "pending_cookies" not in session:
        return redirect(url_for("m.login"))
    if request.method == "GET":
        return render_template("login.html", two_factor=True)
    ip = client_ip()
    if locked_out(ip):
        flash("Too many failed attempts. Wait 5 minutes and try again.", "bad")
        return render_template("login.html", two_factor=True), 429
    ots = OtsLogin(session["pending_cookies"])
    if not ots.two_factor(re.sub(r"\D", "", request.form.get("code", ""))):
        _failures[ip].append(time.time())
        flash("That code didn't work. Codes change every 30 seconds.", "bad")
        return render_template("login.html", two_factor=True), 401
    return finish_login(ots, ip, safe_next(session.get("pending_next")))


def finish_login(ots, ip, nxt):
    """Logged in: admins go to the Manager, everyone else to the web map."""
    me = ots.me()
    if not me or me == DOWN:
        session.clear()
        flash("Couldn't finish logging in. Try again in a moment.", "bad")
        return render_template("login.html", next=nxt), 503
    _failures.pop(ip, None)
    if me["is_admin"]:
        start_session(me["username"])
        dest = nxt or url_for("m.status")
    else:
        session.clear()
        dest = nxt if nxt and not nxt.startswith("/manage") else "/"
    return give_browser(redirect(dest), ots.api.cookies)


@bp.route("/password", methods=["GET", "POST"])
def change_password():
    """Anyone on the team (not just admins) can pick their own password here."""
    if request.method == "GET":
        return render_template("password.html")
    f = request.form
    username = f.get("username", "").strip().lower()
    current, new = f.get("current", ""), f.get("new", "")
    page = lambda code, **kw: (render_template("password.html", username=username, **kw), code)  # noqa: E731
    ip = client_ip()
    if locked_out(ip):
        flash("Too many failed attempts. Wait 5 minutes and try again.", "bad")
        return page(429)
    if new != f.get("again", ""):
        flash("The two new passwords don't match.", "bad")
        return page(400)
    problem = T.check_new_password(username, new)
    if problem:
        flash(problem, "bad")
        return page(400)
    if new == current:
        flash("That's the password you have now. Pick a new one.", "bad")
        return page(400)
    try:
        ots = OtsLogin()
        result = ots.login(username, current) if T.USERNAME_RE.match(username) else "bad"
    except T.TakcxError as e:
        flash(str(e), "bad")
        return page(503)
    if result == "2fa":
        code = re.sub(r"\D", "", f.get("code", ""))
        if not code:
            flash("Your account uses two-factor login. Enter the code from your authenticator app too.", "warn")
            return page(401, need_code=True)
        result = "ok" if ots.two_factor(code) else "bad"
    status, me = ots.api.request("GET", "/api/me") if result == "ok" else (0, None)
    if not isinstance(me, dict) or me.get("username") != username:
        _failures[ip].append(time.time())
        flash("Wrong username, password or code.", "bad")
        return page(401, need_code=bool(f.get("code")))
    profile = T.load_profile(username)
    admin_user = T.read_shell_conf(os.path.join(T.TAKCX_HOME, "admin.conf")).get("OTS_ADMIN_USER", "administrator")
    if not profile or profile.get("type") == "drone" or username == admin_user:
        flash("This account's password can't be changed here. Ask your server admin.", "bad")
        return page(403)
    env = {**os.environ, "TAKCX_NO_QR": "1"}
    try:
        r = subprocess.run(takcx("set-password", username), input=new + "\n", capture_output=True,
                           text=True, timeout=180, env=env, cwd=REPO_DIR)
    except subprocess.TimeoutExpired:
        r = None
    if not r or r.returncode != 0:
        lines = ((r.stdout + r.stderr).strip().splitlines() if r else []) or ["It took too long."]
        flash(f"Couldn't change it: {lines[-1].removeprefix('Error: ')}", "bad")
        return page(500)
    _failures.pop(ip, None)
    return render_template("password.html", done=True, username=username)


@bp.route("/logout", methods=["POST"])
def logout():
    """Log out of the Manager and the web map together."""
    try:
        OtsLogin.from_browser().logout()
    except T.TakcxError:
        pass  # the browser forgets the login below either way
    session.clear()
    return clear_browser(redirect(url_for("m.login", bye=1)))


# --------------------------------------------------------------------------- jobs

JOBS = collections.OrderedDict()
_jobs_lock = threading.Lock()


def start_job(title, commands, back):
    """Run commands (lists of args, no shell) one after another in the background."""
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "title": title, "status": "running", "output": "", "back": back,
           "started": datetime.datetime.now(), "finished": None, "user": session.get("user")}
    with _jobs_lock:
        JOBS[job_id] = job
        while len(JOBS) > 30:
            JOBS.popitem(last=False)
    env = {**os.environ, "TAKCX_NO_QR": "1", "PYTHONUNBUFFERED": "1"}

    def run():
        ok = True
        for cmd in commands:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, text=True, env=env, cwd=REPO_DIR)
                for line in proc.stdout:
                    job["output"] += line
                ok = proc.wait() == 0
            except OSError as e:
                job["output"] += f"Couldn't run {cmd[0]}: {e}\n"
                ok = False
            if not ok:
                break
        job["finished"] = datetime.datetime.now()
        job["status"] = "done" if ok else "failed"

    threading.Thread(target=run, daemon=True).start()
    return redirect(url_for("m.job", job_id=job_id))


def takcx(*args):
    return [sys.executable, TAKCX_PY, *args]


def qr_svg(text):
    if not shutil.which("qrencode"):
        return ""
    r = subprocess.run(["qrencode", "-t", "SVG", "-m", "2", "-s", "4", "-o", "-", text],
                       capture_output=True, text=True)
    svg = r.stdout
    return svg[svg.find("<svg"):] if "<svg" in svg else ""


@bp.route("/jobs/<job_id>")
def job(job_id):
    j = JOBS.get(job_id)
    if not j:
        flash("That job isn't here any more: the Manager restarted (it does after an update; "
              "see Settings → Updates for how it went).", "warn")
        return redirect(url_for("m.jobs"))
    links = []
    for url in re.findall(r"(https://\S+/(?:join|files)/\S+|rtmp://\S+)", j["output"]):
        if url not in [u for u, _ in links]:
            links.append((url, qr_svg(url)))
    return render_template("job.html", job=j, links=links)


@bp.route("/jobs")
def jobs():
    return render_template("jobs.html", jobs=list(reversed(JOBS.values())))


# --------------------------------------------------------------------------- status

def service_state(name):
    if not shutil.which("systemctl"):
        return "unknown"
    return subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True).stdout.strip() or "inactive"


def ots_healthy():
    try:
        conn = http.client.HTTPConnection(T.OTS_API, timeout=4)
        conn.request("GET", "/api/health")
        return conn.getresponse().status == 200
    except OSError:
        return False


@bp.route("/")
def status():
    team = T.read_shell_conf(os.path.join(T.TAKCX_HOME, "team.conf"))
    flag = lambda k: team.get(k, "no").lower() == "yes"  # noqa: E731
    services = [("OpenTAKServer", "opentakserver"), ("TAK connections (TLS)", "eud_handler_ssl"),
                ("Message processing", "cot_parser"), ("Web server", "nginx"),
                ("Message broker", "rabbitmq-server"), ("Database", "postgresql")]
    if flag("RADIO_ENABLED"):
        services.append(("Team radio", "mumble-server"))
    if flag("VIDEO_ENABLED"):
        services.append(("Video server", "mediamtx"))
    if flag("ALERTS_ENABLED"):
        services.append(("Emergency alerts", "takcx-alerts"))
    if flag("PUBLICLAND_ENABLED"):
        services.append(("Public-land maps", "takcx-tiles"))
    rows = [(label, name, service_state(name)) for label, name in services]
    disk = shutil.disk_usage("/")
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "takcx-backup-*.tar.gz")), key=os.path.getmtime)
    last_backup = datetime.datetime.fromtimestamp(os.path.getmtime(backups[-1])) if backups else None
    radio_link = T.radio_link_state() if flag("RADIO_ENABLED") else None
    ots_ok = ots_healthy()
    issues = []
    if not ots_ok:
        issues.append(("OpenTAKServer isn't responding", "opentakserver"))
    issues += [(f"{label} is {state}", name) for label, name, state in rows
               if state not in ("active", "unknown")]
    if radio_link is False:
        issues.append(("Radio logins aren't linked to accounts (nobody can join the radio)", "mumble-server"))
    if disk.free < 3 * 1024 ** 3:
        issues.append((f"Low disk space: {mb(disk.free)} free", None))
    if not backups:
        issues.append(("No backups yet", None))
    elif time.time() - os.path.getmtime(backups[-1]) > 3 * 86400:
        issues.append(("Last backup is more than 3 days old", None))
    tiles = {"people": None, "online": None, "drones": None}
    try:
        people = people_rows()
        tiles = {"people": sum(1 for r in people if r["managed"] and not r["drone"]),
                 "online": sum(1 for r in people if r["online"]),
                 "drones": sum(1 for r in people if r["drone"])}
    except T.TakcxError:
        pass
    addons = [("Team radio", flag("RADIO_ENABLED")), ("Live video", flag("VIDEO_ENABLED")),
              ("Emergency alerts", flag("ALERTS_ENABLED")), ("Public-land maps", flag("PUBLICLAND_ENABLED")),
              ("Aircraft", flag("AIRCRAFT_ENABLED")), ("Elevation data", bool(team.get("ELEVATION_URL"))),
              ("HTTPS certificate", flag("HTTPS_ENABLED"))]
    updates = update_status()
    updates_waiting = bool(updates and (updates["server_behind"] or updates["ui_behind"]
                                        or updates.get("atakcx_behind")))
    return render_template("status.html", rows=rows, ots_ok=ots_ok, disk=disk, issues=issues,
                           updates_waiting=updates_waiting,
                           tiles=tiles, last_backup=last_backup, radio_link=radio_link, addons=addons)


@bp.route("/doctor", methods=["POST"])
def doctor():
    return start_job("Full health check", [takcx("doctor")], url_for("m.status"))


SERVICE_LABELS = {"opentakserver": "OpenTAKServer", "cot_parser": "Message processing",
                  "eud_handler_ssl": "TAK connections (TLS)", "eud_handler": "TAK connections (plain)",
                  "mumble-server": "Team radio", "mediamtx": "Video server", "takcx-alerts": "Emergency alerts",
                  "takcx-tiles": "Public-land maps", "nginx": "Web server"}
RESTARTABLE = ["opentakserver", "cot_parser", "eud_handler_ssl", "eud_handler", "mumble-server",
               "mediamtx", "takcx-alerts", "takcx-tiles", "nginx"]


@bp.route("/restart", methods=["POST"])
def restart_service():
    svc = request.form.get("service", "")
    if svc not in RESTARTABLE:
        abort(400)
    return start_job(f"Restart {svc}", [["sudo", "-n", "systemctl", "restart", svc],
                                        ["sleep", "5"], ["systemctl", "is-active", svc]],
                     request.form.get("back") or url_for("m.status"))


def log_tail(name, max_bytes=400_000):
    """Last lines of an OpenTAKServer log in ~/ots/logs (readable without sudo)."""
    path = os.path.join(T.OTS_DATA_FOLDER, "logs", name)
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - max_bytes))
            return f.read().decode(errors="replace").splitlines()
    except OSError:
        return []


LOG_TIME = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
RADIO_EVENTS = [
    (re.compile(r"Mumble auth: (\S+) has been authenticated"), "ok", "{} logged in"),
    (re.compile(r"Mumble auth: User (\S+) not found"), "bad", "{}: no account with that username (check spelling, all lowercase)"),
    (re.compile(r"Mumble auth: Bad password for (\S+)"), "bad", "{}: wrong password"),
    (re.compile(r"Mumble auth: User (\S+) is deactivated"), "bad", "{}: account is disabled"),
]
TAK_EVENTS = [
    (re.compile(r"(\S+) is ID'ed by cert"), "ok", "{} connected"),
    (re.compile(r"Successful login from (\S+)"), "ok", "{} connected (password)"),
    (re.compile(r"User (\S+) does not exist"), "bad", "{}: account doesn't exist (removed?)"),
    (re.compile(r"User (\S+) is deactivated"), "bad", "{}: account is disabled"),
    (re.compile(r"Wrong password for user (\S+)"), "bad", "{}: wrong password"),
]


def events(lines, patterns, limit=15):
    out = []
    for line in lines:
        t = LOG_TIME.match(line)
        if not t:
            continue  # skip traceback / source-code lines that happen to contain the words
        for rx, kind, text in patterns:
            m = rx.search(line)
            if m:
                out.append({"time": t.group(1), "kind": kind, "text": text.format(m.group(1))})
                break
    return list(reversed(out[-limit:]))


@bp.route("/troubleshoot")
def troubleshoot():
    radio = events(log_tail("opentakserver.log"), RADIO_EVENTS)
    tak = events(log_tail("eud_handler_ssl.log"), TAK_EVENTS)
    errors = []
    for name in ("opentakserver.log", "cot_parser.log", "eud_handler_ssl.log"):
        for line in log_tail(name, 200_000):
            t = LOG_TIME.match(line)
            if t and " - ERROR - " in line:
                msg = line.split(" - ERROR - ", 1)[1][:300]
                errors.append({"time": t.group(1), "where": name.replace(".log", ""), "text": msg})
    errors = sorted(errors, key=lambda e: e["time"])[-15:][::-1]
    states = [(svc, service_state(svc)) for svc in RESTARTABLE]
    return render_template("troubleshoot.html", radio=radio, tak=tak, errors=errors, states=states)


def git(*args):
    r = subprocess.run(["git", "-C", REPO_DIR, *args], capture_output=True, text=True)
    return r.stdout.strip()


_updates = {"at": 0, "data": None}
_updates_lock = threading.Lock()


def update_status(wait=False):
    """What's installed vs. newest, checked at most hourly. Without wait, never blocks a page:
    returns what's known and refreshes in the background."""
    def refresh(blocking):
        if not _updates_lock.acquire(blocking=blocking):
            return  # a check is already running
        try:
            if time.time() - _updates["at"] > 3600:
                data = U.status(timeout=5)
                data["atakcx_behind"] = git_behind()
                _updates.update(at=time.time(), data=data)
        finally:
            _updates_lock.release()
    if time.time() - _updates["at"] > 3600:
        if wait:
            refresh(True)  # waits for a check that's already running instead of starting another
        else:
            threading.Thread(target=refresh, args=(False,), daemon=True).start()
    return _updates["data"]


def git_behind():
    """How many ATAK-CX updates are waiting (None if unknown)."""
    try:
        r = subprocess.run(["git", "-C", REPO_DIR, "fetch", "-q", "origin"], capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    n = git("rev-list", "--count", "HEAD..@{u}")
    return int(n) if n.isdigit() else None


def last_update():
    path = os.path.join(T.TAKCX_HOME, "last-update.log")
    try:
        text = open(path, errors="replace").read()[-20000:]
    except OSError:
        return None
    return {"when": datetime.datetime.fromtimestamp(os.path.getmtime(path)), "log": text,
            "ok": "Update finished" in text}


@bp.route("/update", methods=["POST"])
def update():
    _updates["at"] = 0  # check again afterwards
    return start_job("Update everything", [[os.path.join(REPO_DIR, "setup", "update.sh")]],
                     url_for("m.settings"))


# --------------------------------------------------------------------------- people & drones

def devices(ots):
    """TAK devices OpenTAKServer has seen, with their connection status."""
    out, page = [], 1
    while page <= 5:
        data = ots.call("GET", f"/api/eud?per_page=100&page={page}")
        out += data.get("results", [])
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return out


def people_rows():
    ots = T.connect()
    try:
        devs = devices(ots)
    except T.TakcxError:
        devs = []
    rows = []
    for u in sorted(ots.users(), key=lambda u: u["username"]):
        p = T.load_profile(u["username"]) or {}
        roles = [r.get("name") for r in u.get("roles", [])]
        token_file = os.path.join(T.BUDDIES_DIR, u["username"], "share_token")
        link = None
        if os.path.exists(token_file):
            link = T.share_url(T.load_team(), open(token_file).read().strip())
        mine = [d for d in devs if d.get("username") == u["username"]]
        seen = [parse_time(d.get("last_event_time")) for d in mine]
        seen = [t for t in seen if t]
        rows.append({"username": u["username"], "active": u.get("active"), "profile": p,
                     "admin": "administrator" in roles, "drone": p.get("type") == "drone",
                     "managed": bool(p), "link": link,
                     "online": any(d.get("last_status") == "Connected" for d in mine),
                     "last_seen": max(seen) if seen else None,
                     "devices": [d.get("platform") or "device" for d in mine],
                     "last": u.get("current_login_at") or ""})
    return rows


@bp.route("/people")
def people():
    try:
        rows = people_rows()
    except T.TakcxError as e:
        flash(str(e), "bad")
        rows = []
    return render_template("people.html", rows=[r for r in rows if not r["drone"]],
                           colors=T.TEAM_COLORS, roles=T.ROLES)


@bp.route("/people/add", methods=["POST"])
def people_add():
    f = request.form
    args = ["add", f.get("name", "").strip().lower()]
    if f.get("callsign", "").strip():
        args += ["--callsign", f["callsign"].strip()]
    if f.get("color"):
        args += ["--color", f["color"]]
    if f.get("role"):
        args += ["--role", f["role"]]
    if f.get("admin"):
        args.append("--admin")
    if f.get("share"):
        args.append("--share")
    return start_job(f"Add {args[1]}", [takcx(*args)], url_for("m.people"))


PERSON_ACTIONS = {"share": "Publish link for", "unshare": "Take down link for", "disable": "Disable",
                  "enable": "Enable", "rebuild": "Rebuild files for", "remove": "Remove",
                  "reset-password": "New password for"}


@bp.route("/people/<name>/<action>", methods=["POST"])
def person_action(name, action):
    if action not in PERSON_ACTIONS or not T.USERNAME_RE.match(name):
        abort(404)
    if action == "remove" and request.form.get("confirm") != name:
        flash(f"To remove {name}, type their username in the box first.", "bad")
        return redirect(request.referrer or url_for("m.people"))
    args = [action, name] + (["-y"] if action == "remove" else [])
    back = url_for("m.drones") if request.form.get("from") == "drones" else url_for("m.people")
    return start_job(f"{PERSON_ACTIONS[action]} {name}", [takcx(*args)], back)


@bp.route("/people/<name>/login")
def person_login(name):
    if not T.USERNAME_RE.match(name):
        abort(404)
    profile = T.load_profile(name) or abort(404)
    team = T.load_team()
    token_file = os.path.join(T.BUDDIES_DIR, name, "share_token")
    link = T.share_url(team, open(token_file).read().strip()) if os.path.exists(token_file) else None
    return render_template("person_login.html", name=name, profile=profile, link=link,
                           link_qr=qr_svg(link) if link else "")


@bp.route("/drones")
def drones():
    try:
        rows = [r for r in people_rows() if r["drone"]]
    except T.TakcxError as e:
        flash(str(e), "bad")
        rows = []
    return render_template("drones.html", rows=rows)


@bp.route("/drones/add", methods=["POST"])
def drones_add():
    name = request.form.get("name", "").strip().lower()
    args = ["add-drone", name] + (["--share"] if request.form.get("share") else [])
    return start_job(f"Add drone {name}", [takcx(*args)], url_for("m.drones"))


# --------------------------------------------------------------------------- add-ons

@bp.route("/addons")
def addons():
    team = T.read_shell_conf(os.path.join(T.TAKCX_HOME, "team.conf"))
    ntfy_link = ""
    if team.get("NTFY_TOPIC"):
        ntfy_link = f"{(team.get('NTFY_SERVER') or 'https://ntfy.sh').rstrip('/')}/{team['NTFY_TOPIC']}"
    return render_template("addons.html", ntfy_link=ntfy_link, ntfy_qr=qr_svg(ntfy_link) if ntfy_link else "",
                           gdal=bool(shutil.which("gdalwarp")))


@bp.route("/addons/aircraft", methods=["POST"])
def addons_aircraft():
    if request.form.get("action") == "off":
        return start_job("Turn aircraft off", [takcx("aircraft", "off")], url_for("m.addons"))
    args = ["aircraft", "on"]
    if request.form.get("near", "").strip():
        args += ["--near", request.form["near"].strip()]
    if request.form.get("radius", "").strip().isdigit():
        args += ["--radius", request.form["radius"].strip()]
    return start_job("Aircraft tracking", [takcx(*args)], url_for("m.addons"))


@bp.route("/addons/elevation", methods=["POST"])
def addons_elevation():
    args = ["elevation", "--near", request.form.get("near", "").strip() or "?"]
    if request.form.get("radius", "").strip().isdigit():
        args += ["--radius", request.form["radius"].strip()]
    if request.form.get("level") in ("1", "2"):
        args += ["--level", request.form["level"]]
    return start_job("Build elevation data", [takcx(*args)], url_for("m.addons"))


@bp.route("/addons/alert-test", methods=["POST"])
def addons_alert_test():
    return start_job("Send a test alert", [[OTS_PY, os.path.join(REPO_DIR, "takcx", "alert_bridge.py"), "--test"]],
                     url_for("m.addons"))


# --------------------------------------------------------------------------- plugins

@bp.route("/plugins")
def plugins():
    rows = []
    try:
        rows = T.connect().call("GET", "/api/packages?per_page=100").get("results", [])
    except T.TakcxError as e:
        flash(str(e), "bad")
    return render_template("plugins.html", rows=rows)


@bp.route("/plugins/upload", methods=["POST"])
def plugins_upload():
    f = request.files.get("apk")
    if not f or not f.filename.lower().endswith(".apk"):
        flash("Pick an .apk file.", "bad")
        return redirect(url_for("m.plugins"))
    os.makedirs(UPLOAD_DIR, mode=0o700, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(f.filename))[-120:]
    path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex[:8]}-{safe}")
    f.save(path)
    args = ["plugin", "upload", path]
    if re.fullmatch(r"\d+\.\d+\.\d+", request.form.get("atak_version", "").strip()):
        args += ["--atak-version", request.form["atak_version"].strip()]
    return start_job(f"Upload {safe}", [takcx(*args), ["rm", "-f", path]], url_for("m.plugins"))


@bp.route("/plugins/remove", methods=["POST"])
def plugins_remove():
    pkg = request.form.get("package", "")
    if not re.fullmatch(r"[A-Za-z0-9_.]+", pkg):
        abort(400)
    args = ["plugin", "remove", pkg]
    if re.fullmatch(r"\d+\.\d+\.\d+", request.form.get("atak_version", "")):
        args += ["--atak-version", request.form["atak_version"]]
    return start_job(f"Remove plugin {pkg}", [takcx(*args)], url_for("m.plugins"))


# --------------------------------------------------------------------------- settings

SETTINGS = ["TEAM_NAME", "DEFAULT_TEAM_COLOR", "DEFAULT_ROLE", "COORD_FORMAT", "INCLUDE_MAPS", "RADIO_CHANNELS"]
SECRET_SETTINGS = ["DISCORD_WEBHOOK", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]


def clean_value(v):
    return re.sub(r'["\\`$\r\n]', "", v).strip()[:300]


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    conf_path = os.path.join(T.TAKCX_HOME, "team.conf")
    team = T.read_shell_conf(conf_path)
    if request.method == "GET":
        return render_template("settings.html", colors=T.TEAM_COLORS, roles=T.ROLES,
                               coords=T.COORD_FORMATS, secrets_set={k: bool(team.get(k)) for k in SECRET_SETTINGS},
                               version=git("log", "-1", "--format=%h, %cd", "--date=format:%Y-%m-%d %H:%M"),
                               updates=update_status(wait=True), last_update=last_update())
    f = request.form
    new = {"TEAM_NAME": clean_value(f.get("TEAM_NAME", "")) or team.get("TEAM_NAME", "CX"),
           "DEFAULT_TEAM_COLOR": f.get("DEFAULT_TEAM_COLOR") if f.get("DEFAULT_TEAM_COLOR") in T.TEAM_COLORS else team.get("DEFAULT_TEAM_COLOR", "Cyan"),
           "DEFAULT_ROLE": f.get("DEFAULT_ROLE") if f.get("DEFAULT_ROLE") in T.ROLES else team.get("DEFAULT_ROLE", "Team Member"),
           "COORD_FORMAT": f.get("COORD_FORMAT") if f.get("COORD_FORMAT") in T.COORD_FORMATS else "",
           "INCLUDE_MAPS": "yes" if f.get("INCLUDE_MAPS") else "no",
           "RADIO_CHANNELS": ",".join(c.strip() for c in clean_value(f.get("RADIO_CHANNELS", "")).split(",") if c.strip())
           or team.get("RADIO_CHANNELS", "Main,Team 1,Team 2,Command")}
    changed = [k for k in SETTINGS if new[k] != team.get(k, "")]
    for key in SECRET_SETTINGS:
        if f.get(f"clear_{key}"):
            new[key] = ""
        elif f.get(key, "").strip():
            new[key] = clean_value(f[key])
        else:
            continue
        if new[key] != team.get(key, ""):
            changed.append(key)
    if not changed:
        flash("Nothing changed.", "ok")
        return redirect(url_for("m.settings"))
    for key in changed:
        T.write_shell_conf_value(conf_path, key, new[key])

    commands = []
    if set(changed) & {"TEAM_NAME", "DEFAULT_TEAM_COLOR", "DEFAULT_ROLE", "COORD_FORMAT", "INCLUDE_MAPS"}:
        commands.append(takcx("rebuild", "--all"))
    if "TEAM_NAME" in changed and team.get("WEBMAP_THEME") == "yes":
        commands.append(takcx("webmap-theme", "on"))
    if "RADIO_CHANNELS" in changed and team.get("RADIO_ENABLED") == "yes":
        commands.append([OTS_PY, os.path.join(REPO_DIR, "setup", "radio_channels.py"),
                         *new["RADIO_CHANNELS"].split(",")])
        commands.append(["sudo", "-n", "systemctl", "restart", "mumble-server"])
    if set(changed) & set(SECRET_SETTINGS) and team.get("ALERTS_ENABLED") == "yes":
        commands.append(["sudo", "-n", "systemctl", "restart", "takcx-alerts"])
    readable = ", ".join(k.replace("_", " ").lower() for k in changed)
    if not commands:
        flash(f"Saved: {readable}.", "ok")
        return redirect(url_for("m.settings"))
    return start_job(f"Apply settings ({readable})", commands, url_for("m.settings"))


# --------------------------------------------------------------------------- backups

def backup_files():
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "takcx-backup-*.tar.gz")), key=os.path.getmtime, reverse=True)
    return [{"name": os.path.basename(p), "size": os.path.getsize(p),
             "when": datetime.datetime.fromtimestamp(os.path.getmtime(p))} for p in files]


@bp.route("/backups")
def backups():
    return render_template("backups.html", files=backup_files())


@bp.route("/backups/run", methods=["POST"])
def backups_run():
    return start_job("Back up now", [[os.path.join(REPO_DIR, "setup", "backup.sh")]], url_for("m.backups"))


@bp.route("/backups/<name>/download")
def backups_download(name):
    if name not in [b["name"] for b in backup_files()]:
        abort(404)
    return send_file(os.path.join(BACKUP_DIR, name), as_attachment=True, download_name=name)


# --------------------------------------------------------------------------- template helpers

TEAM_COLOR_HEX = {"White": "#f4f4f4", "Yellow": "#ffe14d", "Orange": "#ff9a2e", "Magenta": "#ff4fd8",
                  "Red": "#ff4d4d", "Maroon": "#9c2b3a", "Purple": "#a45cff", "Dark Blue": "#3b5bdb",
                  "Blue": "#4d8dff", "Cyan": "#3fe0f0", "Teal": "#20b2aa", "Green": "#5ee05e",
                  "Dark Green": "#2f8f3f", "Brown": "#a8703f"}


def parse_time(value):
    """OTS/HTTP dates, ISO times and our own log times -> aware datetime (or None)."""
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        text = str(value).strip()
        dt = None
        try:
            dt = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            pass
        if dt is None:
            try:
                dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive = this server's local time (log files, backups)
    return dt


@bp.app_template_filter("ago")
def ago(value):
    dt = parse_time(value)
    if not dt:
        return "never" if not value else str(value)
    secs = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    if secs < 2 * 86400:
        return "yesterday"
    if secs < 30 * 86400:
        return f"{int(secs // 86400)} days ago"
    return dt.strftime("%b %d, %Y")


@bp.app_template_filter("stamp")
def stamp(value):
    dt = parse_time(value)
    return dt.astimezone().strftime("%a %b %d, %H:%M") if dt else ""


@bp.app_template_filter("team_hex")
def team_hex(color):
    return TEAM_COLOR_HEX.get(color or "", "#8b998e")


@bp.app_template_global()
def icon(name, size=18):
    return Markup(B.icon_svg(name, size))


@bp.app_template_global()
def emblem(team_name, size=40):
    return Markup(B.emblem_svg(team_name, size))


bp.add_app_template_global(B.initials, "initials")


@bp.app_template_filter("mb")
def mb(n):
    return f"{n / 1024 ** 2:.1f} MB" if n < 1024 ** 3 else f"{n / 1024 ** 3:.1f} GB"


@bp.app_template_filter("safe_svg")
def safe_svg(svg):
    # qrencode output only; strip anything that isn't plain SVG drawing just in case.
    return re.sub(r"<script.*?</script>", "", svg, flags=re.S | re.I)


@bp.app_template_global()
def e(text):
    return html.escape(str(text))


def main():
    app = create_app()
    print(f"ATAK-CX Manager on http://127.0.0.1:{PORT}/manage/", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()

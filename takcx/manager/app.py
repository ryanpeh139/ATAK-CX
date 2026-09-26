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
import glob
import html
import http.client
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid

from flask import (Blueprint, Flask, abort, flash, redirect, render_template, request,
                   send_file, session, url_for)

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO_DIR, "takcx"))
import takcx as T  # noqa: E402

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


class OtsLogin:
    """Check a person's OpenTAKServer login (and admin role) via its API."""

    def __init__(self, cookies=None):
        self.api = T.OTS(T.load_team()["SERVER_ADDRESS"])
        self.api.cookies = dict(cookies or {})

    def login(self, username, password):
        status, data = self.api.request("POST", "/api/login", {"username": username, "password": password})
        resp = data.get("response", {}) if isinstance(data, dict) else {}
        if status == 200 and resp.get("tf_required"):
            return "2fa"
        return "ok" if status == 200 else "bad"

    def two_factor(self, code):
        status, _ = self.api.request("POST", "/api/tf-validate", {"code": code})
        return status == 200

    def is_admin(self):
        status, me = self.api.request("GET", "/api/me")
        if status != 200 or not isinstance(me, dict):
            return None
        roles = [r.get("name") for r in me.get("roles", [])]
        return me.get("username") if "administrator" in roles and me.get("active", True) else None


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@bp.before_request
def require_login():
    if request.endpoint in ("m.login", "m.two_factor"):
        pass
    elif not session.get("user"):
        return redirect(url_for("m.login"))
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Form expired. Go back, reload the page and try again.")


@bp.app_context_processor
def template_globals():
    team = T.read_shell_conf(os.path.join(T.TAKCX_HOME, "team.conf"))
    return {"csrf": csrf_token(), "user": session.get("user"), "team": team,
            "running_jobs": sum(1 for j in JOBS.values() if j["status"] == "running")}


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    ip = client_ip()
    if locked_out(ip):
        flash("Too many failed logins. Wait 5 minutes and try again.", "bad")
        return render_template("login.html"), 429
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    try:
        ots = OtsLogin()
        result = ots.login(username, password)
    except T.TakcxError as e:
        flash(str(e), "bad")
        return render_template("login.html"), 503
    if result == "bad":
        _failures[ip].append(time.time())
        flash("Wrong username or password.", "bad")
        return render_template("login.html"), 401
    if result == "2fa":
        session.clear()
        session["pending_cookies"] = ots.api.cookies
        session["pending_user"] = username
        return redirect(url_for("m.two_factor"))
    return finish_login(ots, ip)


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
    return finish_login(ots, ip)


def finish_login(ots, ip):
    admin = ots.is_admin()
    if not admin:
        _failures[ip].append(time.time())
        session.clear()
        flash("That account isn't an administrator. Make one with: takcx add NAME --admin", "bad")
        return render_template("login.html"), 403
    _failures.pop(ip, None)
    session.clear()
    session.permanent = True
    session["user"] = admin
    csrf_token()
    return redirect(url_for("m.status"))


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("m.login"))


# --------------------------------------------------------------------------- jobs

JOBS = collections.OrderedDict()
_jobs_lock = threading.Lock()


def start_job(title, commands, back):
    """Run commands (lists of args, no shell) one after another in the background."""
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "title": title, "status": "running", "output": "", "back": back,
           "started": datetime.datetime.now().strftime("%H:%M:%S"), "user": session.get("user")}
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
    j = JOBS.get(job_id) or abort(404)
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
    last_backup = (datetime.datetime.fromtimestamp(os.path.getmtime(backups[-1])).strftime("%Y-%m-%d %H:%M")
                   if backups else None)
    radio_link = T.radio_link_state() if flag("RADIO_ENABLED") else None
    addons = [("Team radio", flag("RADIO_ENABLED")), ("Live video", flag("VIDEO_ENABLED")),
              ("Emergency alerts", flag("ALERTS_ENABLED")), ("Public-land maps", flag("PUBLICLAND_ENABLED")),
              ("Aircraft", flag("AIRCRAFT_ENABLED")), ("Elevation data", bool(team.get("ELEVATION_URL"))),
              ("HTTPS certificate", flag("HTTPS_ENABLED"))]
    return render_template("status.html", rows=rows, ots_ok=ots_healthy(), disk=disk,
                           last_backup=last_backup, radio_link=radio_link, addons=addons)


@bp.route("/doctor", methods=["POST"])
def doctor():
    return start_job("Full health check", [takcx("doctor")], url_for("m.status"))


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


@bp.route("/update", methods=["POST"])
def update():
    return start_job("Update ATAK-CX", [["git", "-C", REPO_DIR, "pull", "--ff-only"],
                                        ["sudo", "-n", "systemctl", "restart", "takcx-manager"]],
                     url_for("m.settings"))


# --------------------------------------------------------------------------- people & drones

def people_rows():
    ots = T.connect()
    rows = []
    for u in sorted(ots.users(), key=lambda u: u["username"]):
        p = T.load_profile(u["username"]) or {}
        roles = [r.get("name") for r in u.get("roles", [])]
        token_file = os.path.join(T.BUDDIES_DIR, u["username"], "share_token")
        link = None
        if os.path.exists(token_file):
            link = T.share_url(T.load_team(), open(token_file).read().strip())
        rows.append({"username": u["username"], "active": u.get("active"), "profile": p,
                     "admin": "administrator" in roles, "drone": p.get("type") == "drone",
                     "managed": bool(p), "link": link,
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
                               version=git("log", "-1", "--format=%h, %cd", "--date=format:%Y-%m-%d %H:%M"))
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
             "when": datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")} for p in files]


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

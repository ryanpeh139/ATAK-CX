#!/usr/bin/env python3
"""takcx - add and manage buddies on your ATAK-CX TAK server.

Runs on the server, as the same Linux user that runs OpenTAKServer.
Only uses the Python standard library.

  takcx add bob                  create an account + connection packages for bob
  takcx add bob --share          ...and publish a private download link
  takcx list                     show everyone and whether they're enabled
  takcx disable bob / enable bob cut off (or restore) bob's access
  takcx remove bob               delete bob's account for good
  takcx share bob / unshare bob  publish or take down bob's download link
  takcx rebuild --all            rebuild packages after editing team.conf or maps/
  takcx maps                     build a maps-only package anyone can import
  takcx add-drone drone1         a login + stream address for a DJI drone (DJI Fly app)
  takcx aircraft on --near "Denver, CO"   live aircraft on everyone's map
  takcx plugin upload FILE.apk   push an ATAK plugin to everyone's phone
  takcx doctor                   check that everything is running
"""

import argparse
import glob
import html
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

REPO_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MAPS_DIR = os.path.join(REPO_DIR, "maps")
TAKCX_HOME = os.environ.get("TAKCX_HOME", os.path.expanduser("~/takcx"))
BUDDIES_DIR = os.path.join(TAKCX_HOME, "buddies")
OTS_DATA_FOLDER = os.environ.get("OTS_DATA_FOLDER", os.path.expanduser("~/ots"))
OTS_API = os.environ.get("OTS_API", "127.0.0.1:8081")
WEB_ROOT = os.environ.get("TAKCX_WEB_ROOT", "/var/www/html/opentakserver")
OTS_PYTHON = os.environ.get("OTS_PYTHON", os.path.expanduser("~/.opentakserver_venv/bin/python"))
ADSB_API_URL = "https://api.adsb.lol/v2/point"  # free, same format as OpenTAKServer's default

TEAM_COLORS = ["White", "Yellow", "Orange", "Magenta", "Red", "Maroon", "Purple",
               "Dark Blue", "Blue", "Cyan", "Teal", "Green", "Dark Green", "Brown"]
ROLES = ["Team Member", "Team Lead", "HQ", "Sniper", "Medic", "Forward Observer", "RTO", "K9"]
COORD_FORMATS = ["MGRS", "DD", "DM", "DMS", "UTM"]
# OpenTAKServer allows letters, numbers, "_" and "." in usernames. The username
# also becomes the certificate's common name, so keep it to plain ASCII.
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.]{0,31}$")
SERVICES = ["opentakserver", "cot_parser", "eud_handler", "eud_handler_ssl",
            "nginx", "rabbitmq-server", "postgresql"]


class TakcxError(Exception):
    pass


# --------------------------------------------------------------------------- config

def read_shell_conf(path):
    """Read a KEY="value" file (the same file bash can `source`)."""
    conf = {}
    if not os.path.exists(path):
        return conf
    with open(path) as f:
        for line in f:
            m = re.match(r'^\s*([A-Z_][A-Z0-9_]*)=(.*)$', line)
            if not m:
                continue
            value = m.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            conf[m.group(1)] = value
    return conf


def write_shell_conf_value(path, key, value):
    lines = open(path).read().splitlines() if os.path.exists(path) else []
    new_line = f'{key}="{value}"'
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{key}=", line):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def team_flag(name):
    team = read_shell_conf(os.path.join(TAKCX_HOME, "team.conf"))
    return team.get(name, "no").lower() == "yes"


def set_ots_config(values):
    """Set top-level scalar keys in OpenTAKServer's config.yml. Returns True if anything changed."""
    path = os.path.join(OTS_DATA_FOLDER, "config.yml")
    text = open(path).read()
    new = text
    for key, value in values.items():
        line = f"{key}: {value}"
        if re.search(rf"^{key}:.*$", new, flags=re.M):
            new = re.sub(rf"^{key}:.*$", lambda _m: line, new, flags=re.M)
        else:
            new = new.rstrip("\n") + "\n" + line + "\n"
    if new != text:
        with open(path, "w") as f:
            f.write(new)
    return new != text


def restart_ots():
    """Restart OpenTAKServer so it rereads config.yml, then wait until it answers."""
    print("Restarting OpenTAKServer (TAK connections blip and reconnect)...")
    if subprocess.call(["sudo", "systemctl", "restart", "opentakserver"]) != 0:
        raise TakcxError("Couldn't restart it. Run: sudo systemctl restart opentakserver")
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://{OTS_API}/api/health", timeout=3):
                return
        except OSError:
            time.sleep(3)
    raise TakcxError("OpenTAKServer didn't come back. Check ~/ots/logs/opentakserver.log")


def read_ots_config():
    """Pull the few top-level scalar settings we need out of OTS's config.yml."""
    conf = {
        "OTS_CA_PASSWORD": "atakatak",
        "OTS_SSL_STREAMING_PORT": "8089",
        "OTS_MARTI_HTTPS_PORT": "8443",
        "OTS_CA_FOLDER": os.path.join(OTS_DATA_FOLDER, "ca"),
    }
    path = os.path.join(OTS_DATA_FOLDER, "config.yml")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                m = re.match(r"^([A-Z_][A-Z0-9_]*):\s*(.*?)\s*$", line)
                if m and m.group(1) in conf and m.group(2):
                    conf[m.group(1)] = m.group(2).strip("'\"")
    return conf


def load_team():
    team = read_shell_conf(os.path.join(TAKCX_HOME, "team.conf"))
    if not team.get("SERVER_ADDRESS"):
        raise TakcxError(f"SERVER_ADDRESS is not set in {TAKCX_HOME}/team.conf. "
                         "Run setup/install-server.sh first, or edit that file.")
    team.setdefault("TEAM_NAME", "CX")
    team.setdefault("DEFAULT_TEAM_COLOR", "Cyan")
    team.setdefault("DEFAULT_ROLE", "Team Member")
    team.setdefault("INCLUDE_MAPS", "yes")
    return team


def load_admin():
    admin = read_shell_conf(os.path.join(TAKCX_HOME, "admin.conf"))
    if not admin.get("OTS_ADMIN_PASSWORD"):
        raise TakcxError(f"No admin login found in {TAKCX_HOME}/admin.conf. "
                         "Run setup/install-server.sh first.")
    admin.setdefault("OTS_ADMIN_USER", "administrator")
    return admin


# --------------------------------------------------------------------------- OTS API

class OTS:
    """Tiny client for the OpenTAKServer web API on localhost.

    Every request carries Host: <public address> so that anything OTS
    generates from the request URL (e.g. certificate records) names the
    public server, not 127.0.0.1.
    """

    def __init__(self, host_header):
        self.host_header = host_header
        self.cookies = {}

    def request(self, method, path, body=None, raw=None, content_type=None):
        conn = http.client.HTTPConnection(OTS_API, timeout=300)
        headers = {"Host": self.host_header, "Accept": "application/json"}
        if raw is not None:
            headers["Content-Type"] = content_type
        elif body is not None:
            headers["Content-Type"] = "application/json"
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if "XSRF-TOKEN" in self.cookies:
            headers["X-XSRF-Token"] = self.cookies["XSRF-TOKEN"]
        try:
            payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
        except OSError as e:
            raise TakcxError(f"Can't reach OpenTAKServer at {OTS_API} ({e}). "
                             "Is it running? Try: takcx doctor")
        for header, value in resp.getheaders():
            if header.lower() == "set-cookie":
                name, _, rest = value.partition("=")
                self.cookies[name.strip()] = rest.split(";", 1)[0]
        raw = resp.read().decode(errors="replace")
        conn.close()
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {"raw": raw}
        return resp.status, data

    @staticmethod
    def error_text(data):
        if isinstance(data, dict):
            if data.get("error"):
                return data["error"]
            errors = data.get("response", {}).get("errors")
            if errors:
                return "; ".join(errors)
        return json.dumps(data)[:300]

    def login(self, username, password):
        status, data = self.request("POST", "/api/login",
                                    {"username": username, "password": password})
        if status != 200:
            raise TakcxError(f"Admin login failed: {self.error_text(data)}")

    def call(self, method, path, body=None, ok_statuses=(200,)):
        status, data = self.request(method, path, body)
        if status not in ok_statuses or (isinstance(data, dict) and data.get("success") is False):
            raise TakcxError(f"{path}: {self.error_text(data)}")
        return data

    def upload(self, path, fields, file_field, file_path):
        boundary = "takcx" + secrets.token_hex(12)
        parts = []
        for name, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                         f"{value}\r\n".encode())
        filename = os.path.basename(file_path)
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                     f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
        with open(file_path, "rb") as f:
            parts.append(f.read())
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        status, data = self.request("POST", path, raw=b"".join(parts),
                                    content_type=f"multipart/form-data; boundary={boundary}")
        if status != 200 or (isinstance(data, dict) and data.get("success") is False):
            raise TakcxError(f"{path}: {data.get('errors') or self.error_text(data)}")
        return data

    def users(self):
        users, page = [], 1
        while True:
            data = self.call("GET", f"/api/users?per_page=100&page={page}")
            users.extend(data.get("results", []))
            if page >= data.get("total_pages", 1):
                return users
            page += 1

    def find_user(self, username):
        return next((u for u in self.users() if u["username"] == username), None)


def connect(team=None):
    team = team or load_team()
    admin = load_admin()
    ots = OTS(team["SERVER_ADDRESS"])
    ots.login(admin["OTS_ADMIN_USER"], admin["OTS_ADMIN_PASSWORD"])
    return ots


def join_aircraft_groups(ots, username):
    """Aircraft are sent to OpenTAKServer's "ADS-B" group. Joining any group stops a
    user getting the default (__ANON__) team traffic, so join both."""
    for direction, groups in (("OUT", ["__ANON__", "ADS-B"]), ("IN", ["__ANON__"])):
        try:
            ots.call("PUT", "/api/users/groups",
                     {"username": username, "direction": direction, "groups": groups})
        except TakcxError as e:
            if "already" not in str(e).lower():
                raise


# --------------------------------------------------------------------------- packages

def new_password(length=16):
    # No look-alike characters, and none of the "@" / ":" that OTS rejects.
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "Il1O0o")
    return "".join(secrets.choice(alphabet) for _ in range(length))


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-") or "team"


def stable_uid(*parts):
    """Same package UID every rebuild, so re-importing replaces instead of duplicating."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "takcx:" + ":".join(parts)))


def entry(key, value):
    cls = "Boolean" if isinstance(value, bool) else "String"
    value = str(value).lower() if isinstance(value, bool) else xml_escape(str(value))
    return f'    <entry key="{key}" class="class java.lang.{cls}">{value}</entry>'


def manifest(uid, name, entries, delete_after_import=False):
    lines = ['<MissionPackageManifest version="2">', "  <Configuration>",
             f'    <Parameter name="uid" value="{uid}"/>',
             f'    <Parameter name="name" value="{xml_escape(name)}"/>']
    if delete_after_import:
        lines.append('    <Parameter name="onReceiveDelete" value="true"/>')
    lines += ["  </Configuration>", "  <Contents>"]
    lines += [f'    <Content ignore="false" zipEntry="{xml_escape(e)}"/>' for e in entries]
    lines += ["  </Contents>", "</MissionPackageManifest>", ""]
    return "\n".join(lines)


def map_files():
    return sorted(glob.glob(os.path.join(MAPS_DIR, "*.xml")))


def build_maps_zip(team, path):
    files = map_files()
    folder = "maps"
    entries = [f"{folder}/{os.path.basename(f)}" for f in files]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f, e in zip(files, entries):
            z.write(f, e)
        z.writestr("MANIFEST/manifest.xml",
                   manifest(stable_uid(team["SERVER_ADDRESS"], "maps"),
                            f"{team['TEAM_NAME']} maps", entries))
    return len(files)


def atak_prefs(team, ots_conf, username, profile):
    server = team["SERVER_ADDRESS"]
    port = ots_conf["OTS_SSL_STREAMING_PORT"]
    pw = ots_conf["OTS_CA_PASSWORD"]
    lines = ["<?xml version='1.0' standalone='yes'?>", "<preferences>",
             '  <preference version="1" name="cot_streams">',
             '    <entry key="count" class="class java.lang.Integer">1</entry>',
             entry("description0", team["TEAM_NAME"]),
             entry("enabled0", True),
             entry("connectString0", f"{server}:{port}:ssl"),
             entry("caLocation0", "cert/truststore-root.p12"),
             entry("caPassword0", pw),
             entry("clientPassword0", pw),
             entry("certificateLocation0", f"cert/{username}.p12"),
             "  </preference>",
             '  <preference version="1" name="com.atakmap.app_preferences">',
             entry("locationCallsign", profile["callsign"]),
             entry("locationTeam", profile["color"]),
             entry("atakRoleType", profile["role"]),
             entry("displayServerConnectionWidget", True),
             entry("deviceProfileEnableOnConnect", True),
             entry("appMgmtEnableUpdateServer", True),
             entry("atakUpdateServerUrl",
                   f"https://{server}:{ots_conf['OTS_MARTI_HTTPS_PORT']}/api/packages"),
             entry("repoStartupSync", True),
             entry("updateServerCaLocation", "cert/truststore-root.p12"),
             entry("updateServerCaPassword", pw)]
    if team.get("COORD_FORMAT"):
        lines.append(entry("coord_display_pref", team["COORD_FORMAT"]))
    lines += ["  </preference>", "</preferences>", ""]
    return "\n".join(lines)


def itak_prefs(team, ots_conf, username):
    pw = ots_conf["OTS_CA_PASSWORD"]
    return "\n".join([
        "<?xml version='1.0' standalone='yes'?>", "<preferences>",
        '  <preference version="1" name="cot_streams">',
        '    <entry key="count" class="class java.lang.Integer">1</entry>',
        entry("description0", team["TEAM_NAME"]),
        entry("enabled0", True),
        entry("connectString0",
              f"{team['SERVER_ADDRESS']}:{ots_conf['OTS_SSL_STREAMING_PORT']}:ssl"),
        "  </preference>",
        '  <preference version="1" name="com.atakmap.app_preferences">',
        entry("displayServerConnectionWidget", True),
        entry("caLocation", "cert/truststore-root.p12"),
        entry("caPassword", pw),
        entry("clientPassword", pw),
        entry("certificateLocation", f"cert/{username}.p12"),
        "  </preference>", "</preferences>", ""])


def cert_paths(ots_conf, username):
    ca = ots_conf["OTS_CA_FOLDER"]
    return (os.path.join(ca, "truststore-root.p12"),
            os.path.join(ca, "certs", username, f"{username}.p12"))


def build_packages(team, ots_conf, username, profile):
    """Write the ATAK/WinTAK package, the iTAK package, maps and a how-to page."""
    truststore, user_p12 = cert_paths(ots_conf, username)
    for f in (truststore, user_p12):
        if not os.path.exists(f):
            raise TakcxError(f"Missing certificate file {f}")

    out = os.path.join(BUDDIES_DIR, username)
    os.makedirs(out, mode=0o700, exist_ok=True)
    for old in glob.glob(os.path.join(out, "*.zip")):
        os.remove(old)
    base = f"{slug(team['TEAM_NAME'])}-{username}"
    server = team["SERVER_ADDRESS"]
    files = {}

    # ATAK + WinTAK: an outer package wrapping an inner connection package
    # (WinTAK needs the nesting), plus an inner maps package. This mirrors the
    # layout OpenTAKServer itself generates.
    conn_folder = "connection"
    conn_entries = [f"{conn_folder}/preference.pref", f"{conn_folder}/truststore-root.p12",
                    f"{conn_folder}/{username}.p12"]
    inner = os.path.join(out, "connection.zip.tmp")
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(conn_entries[0], atak_prefs(team, ots_conf, username, profile))
        z.write(truststore, conn_entries[1])
        z.write(user_p12, conn_entries[2])
        z.writestr("MANIFEST/manifest.xml",
                   manifest(stable_uid(server, username, "connection"),
                            f"{team['TEAM_NAME']} server connection", conn_entries,
                            delete_after_import=True))
    outer_entries = ["packages/connection.zip"]
    maps_tmp = None
    if team.get("INCLUDE_MAPS", "yes").lower() == "yes" and map_files():
        maps_tmp = os.path.join(out, "maps.zip.tmp")
        build_maps_zip(team, maps_tmp)
        outer_entries.append("packages/maps.zip")

    files["atak"] = f"{base}-ATAK.zip"
    with zipfile.ZipFile(os.path.join(out, files["atak"]), "w", zipfile.ZIP_DEFLATED) as z:
        z.write(inner, outer_entries[0])
        if maps_tmp:
            z.write(maps_tmp, outer_entries[1])
        z.writestr("MANIFEST/manifest.xml",
                   manifest(stable_uid(server, username, "atak"),
                            f"{team['TEAM_NAME']} - {profile['callsign']}", outer_entries))
    os.remove(inner)

    # iTAK: flat zip with config.pref at the root.
    files["itak"] = f"{base}-iTAK.zip"
    with zipfile.ZipFile(os.path.join(out, files["itak"]), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("config.pref", itak_prefs(team, ots_conf, username))
        z.write(truststore, "truststore-root.p12")
        z.write(user_p12, f"{username}.p12")

    if maps_tmp:
        files["maps"] = f"{slug(team['TEAM_NAME'])}-maps.zip"
        shutil.move(maps_tmp, os.path.join(out, files["maps"]))

    # Holds their web password too, so owner-only.
    fd = os.open(os.path.join(out, "profile.json"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(profile, f, indent=2)
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(onboarding_page(team, username, profile, files))
    return out, files


# --------------------------------------------------------------------------- onboarding page

PAGE = string.Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Join $team</title>
<style>
  :root { --bg:#f6f7f4; --card:#fff; --ink:#1d231f; --muted:#5b665e; --accent:#2f6b3f; --line:#dfe3dc; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#151916; --card:#1e241f; --ink:#e7ece6; --muted:#9aa69c; --accent:#7fc58f; --line:#2f3831; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  main { max-width:640px; margin:0 auto; padding:24px 16px 48px; }
  h1 { font-size:1.6rem; margin:0 0 4px; }
  h2 { font-size:1.15rem; margin:0 0 8px; }
  a { color:var(--accent); }
  .sub { color:var(--muted); margin:0 0 20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:16px; margin:0 0 16px; }
  .card.mine { border:2px solid var(--accent); }
  .btn { display:inline-block; background:var(--accent); color:var(--bg); text-decoration:none;
         font-weight:600; padding:10px 16px; border-radius:8px; margin:4px 0; }
  .btn.alt { background:transparent; color:var(--accent); border:1px solid var(--accent); }
  ol { padding-left:1.25rem; margin:8px 0 0; }
  li { margin:4px 0; }
  code { background:var(--line); padding:1px 5px; border-radius:4px; }
  .tag { font-size:.75rem; font-weight:600; color:var(--accent); text-transform:uppercase;
         letter-spacing:.05em; display:none; }
  .mine .tag { display:block; }
  dl { display:grid; grid-template-columns:max-content 1fr; gap:4px 12px; margin:0; }
  dt { color:var(--muted); }
  dd { margin:0; word-break:break-all; }
</style>
</head>
<body>
<main>
  <h1>Welcome to $team, $callsign</h1>
  <p class="sub">This page is just for you. It sets up your phone or PC to join the team map.
  Don't forward it: the files below are your personal login.</p>

  <div class="card" id="android">
    <span class="tag">Your device</span>
    <h2>Android: ATAK</h2>
    <ol>
      <li>Install <a href="https://play.google.com/store/apps/details?id=com.atakmap.app.civ">ATAK-CIV</a>
          from the Play Store, open it and allow the permissions it asks for.</li>
      <li>Download your package: <br><a class="btn" href="$atak_zip" download>$atak_zip</a></li>
      <li>In ATAK, tap the <b>&#9776; menu</b>, then <b>Import</b>, then <b>Local SD</b>, and pick
          <code>$atak_zip</code> from your <b>Download</b> folder.</li>
      <li>After a few seconds the dot on the server icon turns <b>green</b>. You're in.
          Your callsign, team color and the team's maps are already set up.</li>
    </ol>
  </div>

  <div class="card" id="ios">
    <span class="tag">Your device</span>
    <h2>iPhone / iPad: iTAK</h2>
    <ol>
      <li>Install <a href="https://apps.apple.com/app/itak/id1561656396">iTAK</a> from the App Store.</li>
      <li>Download your package: <br><a class="btn" href="$itak_zip" download>$itak_zip</a>
          <br>It lands in the Files app, under <b>Downloads</b>.</li>
      <li>In iTAK open <b>Settings &rarr; Network &rarr; Servers</b>, tap <b>+</b>, choose
          <b>Upload Server Package</b> and pick <code>$itak_zip</code>.</li>
      <li>Set your callsign to <b>$callsign</b> and your team color to <b>$color</b> in iTAK's settings.</li>
    </ol>
  </div>

  <div class="card" id="windows">
    <span class="tag">Your device</span>
    <h2>Windows: WinTAK</h2>
    <ol>
      <li>Download WinTAK-CIV from <a href="https://tak.gov/products/wintak-civ">tak.gov</a>
          (free account) and install it.</li>
      <li>Download the same package as Android: <br><a class="btn" href="$atak_zip" download>$atak_zip</a></li>
      <li>Drag the zip onto the WinTAK map window and accept the import.</li>
    </ol>
  </div>

  $alerts_card

  $chat_card

  $radio_card

  $video_card

  $maps_card

  <div class="card">
    <h2>Your details</h2>
    <dl>
      <dt>Callsign</dt><dd>$callsign</dd>
      <dt>Team color</dt><dd>$color</dd>
      <dt>Role</dt><dd>$role</dd>
      <dt>Server</dt><dd>$server</dd>
      $web_login
    </dl>
  </div>

  <p class="sub">Stuck? Check that your phone's date and time are set automatically, then
  ask whoever sent you this link.</p>
</main>
<script>
  // Highlight the section for the device this page was opened on.
  var ua = navigator.userAgent, id = /android/i.test(ua) ? "android"
    : /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1) ? "ios"
    : /windows/i.test(ua) ? "windows" : null;
  if (id) {
    var el = document.getElementById(id);
    el.classList.add("mine");
    el.parentNode.insertBefore(el, el.parentNode.querySelector(".card"));
  }
</script>
</body>
</html>
""")


def onboarding_page(team, username, profile, files):
    h = html.escape
    maps_card = ""
    if files.get("maps"):
        maps_card = (
            '<div class="card"><h2>Maps</h2><p>Satellite, topo and street maps are already inside '
            'your ATAK/WinTAK package. In ATAK, open <b>&#9776; &rarr; Maps &amp; Favorites</b> to '
            'switch between them. No signal where you&rsquo;re going? Download the area first: in '
            '<b>Maps &amp; Favorites</b>, pick a map, tap the download button, draw a box around '
            'the area and choose how much detail you want.</p>'
            f'<a class="btn alt" href="{h(files["maps"])}" download>Maps only ({h(files["maps"])})</a></div>')
    radio = team.get("RADIO_ENABLED", "no").lower() == "yes"
    password = profile.get("password") if profile.get("show_web_login") else None
    web_login = ""
    if password:
        web_login = (f'<dt>Web map</dt><dd><a href="https://{h(team["SERVER_ADDRESS"])}/">'
                     f'https://{h(team["SERVER_ADDRESS"])}/</a></dd>'
                     f'<dt>Username</dt><dd>{h(username)}</dd>'
                     f'<dt>Password</dt><dd>{h(password)}'
                     f'{" (web map and radio)" if radio else ""}</dd>')
    return PAGE.substitute(
        team=h(team["TEAM_NAME"]), callsign=h(profile["callsign"]), color=h(profile["color"]),
        role=h(profile["role"]), server=h(team["SERVER_ADDRESS"]),
        atak_zip=h(files["atak"]), itak_zip=h(files["itak"]),
        maps_card=maps_card, web_login=web_login, chat_card=CHAT_CARD,
        video_card=VIDEO_CARD if team.get("VIDEO_ENABLED", "no").lower() == "yes" else "",
        alerts_card=alerts_card(team),
        radio_card=radio_card(team, username, password) if radio else "")


CHAT_CARD = """<div class="card">
    <h2>Team chat</h2>
    <p>Chat is built into the app. It goes through the team's own server, encrypted.</p>
    <ul>
      <li><b>ATAK / WinTAK:</b> tap the chat icon (speech bubbles), or <b>&#9776; &rarr; Chat</b>.
          <b>All Chat Rooms</b> reaches everyone, your team color's room reaches your team,
          or tap someone on the map to message just them.</li>
      <li><b>iTAK:</b> tap <b>Chat</b>.</li>
      <li>You can also send photos, markers and routes to people from the map.</li>
    </ul>
  </div>"""


VIDEO_CARD = """<div class="card">
    <h2>Live video</h2>
    <p>Watch the team's drone and camera streams.</p>
    <ul>
      <li><b>ATAK:</b> open <b>&#9776; &rarr; Video Player</b>, tap the download (cloud) button to get
          the list from the server, pick a stream and tap <b>OK</b>. Then edit that stream and enter
          your username and password (below).</li>
      <li><b>Any phone or computer:</b> open the web map, log in, go to <b>Video Streams</b> and tap
          <b>Watch</b>.</li>
      <li><b>Stream your own camera:</b> on the web map, <b>Video Streams &rarr; Start Streaming</b>.</li>
    </ul>
  </div>"""


def alerts_card(team):
    if team.get("ALERTS_ENABLED", "no").lower() != "yes" or not team.get("NTFY_TOPIC"):
        return ""
    h = html.escape
    link = f"{(team.get('NTFY_SERVER') or 'https://ntfy.sh').rstrip('/')}/{team['NTFY_TOPIC']}"
    return f"""<div class="card">
    <h2>Emergency alerts on your phone</h2>
    <p>If anyone hits the emergency button in ATAK, you get a loud notification with a map link,
    even when ATAK is closed. Worth setting up for family at home too.</p>
    <ol>
      <li>Install <b>ntfy</b>:
          <a href="https://play.google.com/store/apps/details?id=io.heckel.ntfy">Android</a> or
          <a href="https://apps.apple.com/app/ntfy/id1625396347">iPhone</a>.</li>
      <li>In ntfy tap <b>+</b> and subscribe to <b>{h(team['NTFY_TOPIC'])}</b>, or open
          <a href="{h(link)}">this link</a> on your phone.</li>
      <li>Allow notifications when asked.</li>
    </ol>
    <p>Keep the topic name within the team: anyone who has it can read the alerts.</p>
  </div>"""


def radio_card(team, username, password):
    h = html.escape
    server = team["SERVER_ADDRESS"]
    channels = [c.strip() for c in team.get("RADIO_CHANNELS", "Main").split(",") if c.strip()]
    title = urllib.parse.quote(f"{team['TEAM_NAME']} Radio")
    login = urllib.parse.quote(username) + (f":{urllib.parse.quote(password)}" if password else "")
    link = f"mumble://{login}@{server}:64738/?title={title}&version=1.2.0"
    pw_hint = "the password below" if password else "your password (ask whoever sent this page)"
    return f"""<div class="card">
    <h2>Team radio</h2>
    <p>Push-to-talk voice channels, like walkie-talkies over the internet. Only the team can get in.</p>
    <ol>
      <li>Install <a href="https://play.google.com/store/apps/details?id=se.lublin.mumla">Mumla</a>
          (Android), or <a href="https://www.mumble.info/downloads/">Mumble</a> (Windows/Mac).
          On iPhone, search the App Store for <b>Mumble</b>.</li>
      <li><a class="btn" href="{h(link)}">Open the radio</a><br>
          If that doesn't open the app, add a server by hand: address <b>{h(server)}</b>,
          port <b>64738</b>, username <b>{h(username)}</b>, and {pw_hint}.</li>
      <li>The first time, the app asks about the server's certificate. Tap <b>Accept</b>.</li>
      <li>Switch to push-to-talk. In Mumla: <b>Settings &rarr; Audio &rarr; Transmit mode &rarr;
          Push to talk</b>. Hold the big button to talk.</li>
      <li>Tap a channel to switch. Everyone in the same channel hears you. Channels:
          <b>{h(", ".join(channels))}</b>.</li>
    </ol>
  </div>"""


# --------------------------------------------------------------------------- helpers

def check_username(name):
    name = name.strip().lower()
    if not USERNAME_RE.match(name):
        raise TakcxError(f"'{name}' isn't a valid username. Use lowercase letters, numbers, "
                         "'_' or '.', up to 32 characters, starting with a letter or number.")
    return name


def pick(value, options, what):
    for option in options:
        if value.lower() == option.lower():
            return option
    raise TakcxError(f"Unknown {what} '{value}'. Pick one of: " + ", ".join(options))


def print_qr(text):
    if shutil.which("qrencode"):
        subprocess.call(["qrencode", "-t", "ANSIUTF8", "-m", "2", text])


def share_url(team, token):
    return f"https://{team['SERVER_ADDRESS']}/join/{token}/index.html"


def load_profile(username):
    path = os.path.join(BUDDIES_DIR, username, "profile.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


# --------------------------------------------------------------------------- commands

def cmd_add(args):
    team = load_team()
    ots_conf = read_ots_config()
    username = check_username(args.name)
    profile = {
        "callsign": (args.callsign or username).strip(),
        "color": pick(args.color or team["DEFAULT_TEAM_COLOR"], TEAM_COLORS, "team color"),
        "role": pick(args.role or team["DEFAULT_ROLE"], ROLES, "role"),
        "admin": bool(args.admin),
        "created": datetime.now().isoformat(timespec="seconds"),
        "show_web_login": not args.no_web_login,
    }
    if team.get("COORD_FORMAT"):
        team["COORD_FORMAT"] = pick(team["COORD_FORMAT"], COORD_FORMATS, "COORD_FORMAT")

    ots = connect(team)
    if ots.find_user(username):
        raise TakcxError(f"{username} already exists. Use `takcx rebuild {username}` to remake "
                         f"their packages, or `takcx remove {username}` first.")

    password = new_password()
    roles = ["administrator"] if args.admin else ["user"]
    print(f"Creating account {username}...")
    ots.call("POST", "/api/user/add", {"username": username, "password": password,
                                        "confirm_password": password, "roles": roles})
    print("Issuing certificate...")
    ots.call("POST", "/api/certificate", {"username": username})
    if team_flag("AIRCRAFT_ENABLED"):
        join_aircraft_groups(ots, username)

    profile["password"] = password
    out, files = build_packages(team, ots_conf, username, profile)
    creds = os.path.join(out, "credentials.txt")
    with open(creds, "w") as f:
        f.write(f"username: {username}\npassword: {password}\n"
                f"web map: https://{team['SERVER_ADDRESS']}/\n")
    os.chmod(creds, 0o600)

    print(f"\nDone. {profile['callsign']} ({profile['color']}, {profile['role']}) is set up.")
    print(f"Files are in {out}/:")
    for f in sorted(os.listdir(out)):
        print(f"  {f}")
    if args.share:
        do_share(team, username)
    else:
        print(f"\nSend {files['atak']} (Android/Windows) or {files['itak']} (iPhone) to them "
              "over Signal, email, AirDrop etc., or run:\n"
              f"  takcx share {username}\nto get a private download link.")


def cmd_rebuild(args):
    team = load_team()
    ots_conf = read_ots_config()
    names = sorted(os.listdir(BUDDIES_DIR)) if args.all else [check_username(n) for n in args.names]
    if not names:
        raise TakcxError("Give one or more usernames, or --all.")
    for username in names:
        profile = load_profile(username)
        if profile is None:
            print(f"Skipping {username}: no profile.json (was it added with takcx?)")
            continue
        if profile.get("type") == "drone":
            write_drone_page(team, username, profile)
            print(f"Rebuilt {username} (drone)")
            continue
        if args.color:
            profile["color"] = pick(args.color, TEAM_COLORS, "team color")
        if args.role:
            profile["role"] = pick(args.role, ROLES, "role")
        if args.callsign:
            profile["callsign"] = args.callsign
        build_packages(team, ots_conf, username, profile)
        token_file = os.path.join(BUDDIES_DIR, username, "share_token")
        if os.path.exists(token_file):
            publish(username, open(token_file).read().strip())
        print(f"Rebuilt {username}")
    print("People who already joined need to import their new package for changes to apply.")


def cmd_list(args):
    team = load_team()
    ots = connect(team)
    users = sorted(ots.users(), key=lambda u: u["username"])
    print(f"{'USERNAME':<20} {'STATUS':<9} {'CALLSIGN':<16} {'SHARED':<7} LAST LOGIN")
    for u in users:
        profile = load_profile(u["username"]) or {}
        shared = os.path.exists(os.path.join(BUDDIES_DIR, u["username"], "share_token"))
        roles = [r.get("name") for r in u.get("roles", [])]
        status = "enabled" if u.get("active") else "DISABLED"
        callsign = profile.get("callsign", "-") + (" *" if "administrator" in roles else "")
        if profile.get("type") == "drone":
            callsign = "(drone)"
        print(f"{u['username']:<20} {status:<9} {callsign:<16} {'yes' if shared else '-':<7} "
              f"{u.get('current_login_at') or '-'}")
    print("\n* = administrator")


def radio_enabled():
    team = read_shell_conf(os.path.join(TAKCX_HOME, "team.conf"))
    return team.get("RADIO_ENABLED", "no").lower() == "yes"


def radio_link_state():
    """True if Mumble's newest authenticator event is OpenTAKServer attaching, False if
    it was removed or failed since, None if the log can't be read."""
    log = ""
    for cmd in (["sudo", "-n", "journalctl", "-u", "mumble-server", "-n", "300", "--no-pager"],
                ["sudo", "-n", "tail", "-n", "300", "/var/log/mumble-server/mumble-server.log"]):
        try:
            log += subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
    events = re.findall(r"(Set Ice Authenticator|Removed Ice Authenticator)", log)
    return events[-1].startswith("Set") if events else None


def kick_connections(args):
    """OTS only checks accounts when a device connects, so restart the TAK listeners
    to drop live sessions. Everyone else's app reconnects on its own within seconds."""
    if args.no_kick or not shutil.which("systemctl"):
        print("Their current connection stays up until their app reconnects.")
        return
    print("Dropping live connections so it takes effect now (others reconnect automatically)...")
    services = ["eud_handler_ssl", "eud_handler"]
    if radio_enabled():
        # Also restarts OpenTAKServer, which re-links radio logins (see setup/enable-radio.sh).
        services.append("mumble-server")
    if subprocess.call(["sudo", "systemctl", "restart", *services]) != 0:
        print(f"Couldn't restart them. Run: sudo systemctl restart {' '.join(services)}")


def cmd_disable(args):
    ots = connect()
    username = check_username(args.name)
    ots.call("POST", "/api/user/deactivate", {"username": username})
    # OpenTAKServer's video login ignores "disabled", so also swap in a password
    # nobody knows. `takcx enable` puts their real one back.
    ots.call("POST", "/api/user/password/reset",
             {"username": username, "new_password": new_password(32)})
    unshare(username, quiet=True)
    kick_connections(args)
    print(f"{username} is disabled: no map, radio, video or web login. "
          f"Undo with: takcx enable {username}")


def cmd_enable(args):
    ots = connect()
    username = check_username(args.name)
    ots.call("POST", "/api/user/activate", {"username": username})
    profile = load_profile(username) or {}
    if profile.get("password"):
        ots.call("POST", "/api/user/password/reset",
                 {"username": username, "new_password": profile["password"]})
        print(f"{username} is enabled again, with their old password.")
    else:
        print(f"{username} is enabled again, but takcx doesn't know their old password. "
              "Set a new one in the web admin (Users) and give it to them.")


def cmd_remove(args):
    username = check_username(args.name)
    if not args.yes:
        answer = input(f"Permanently delete {username} and their packages? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return
    ots = connect()
    if ots.find_user(username):
        ots.call("POST", "/api/user/delete", {"username": username})
    unshare(username, quiet=True)
    shutil.rmtree(os.path.join(BUDDIES_DIR, username), ignore_errors=True)
    kick_connections(args)
    print(f"{username} removed. They can no longer log in or connect.")


def publish(username, token):
    src = os.path.join(BUDDIES_DIR, username)
    dest = os.path.join(WEB_ROOT, "join", token)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    for f in os.listdir(src):
        if f.endswith(".zip") or f == "index.html":
            shutil.copy(os.path.join(src, f), dest)


def do_share(team, username):
    src = os.path.join(BUDDIES_DIR, username)
    if not os.path.exists(os.path.join(src, "index.html")):
        raise TakcxError(f"No packages for {username}. Run `takcx add {username}` first.")
    if not os.access(WEB_ROOT, os.W_OK):
        raise TakcxError(f"Can't write to {WEB_ROOT}. Was OpenTAKServer installed with "
                         "setup/install-server.sh?")
    token_file = os.path.join(src, "share_token")
    token = (open(token_file).read().strip() if os.path.exists(token_file)
             else secrets.token_urlsafe(18))
    publish(username, token)
    with open(token_file, "w") as f:
        f.write(token)
    url = share_url(team, token)
    print(f"\nPrivate link for {username} (treat it like a password):\n\n  {url}\n")
    print_qr(url)
    if team.get("HTTPS_ENABLED", "no").lower() != "yes":
        print("Note: HTTPS isn't set up yet, so their browser will show a security warning\n"
              "and they'll need to tap Advanced -> Proceed. Run setup/enable-https.sh to fix.")
    print(f"Take it down once they've joined: takcx unshare {username}")


def unshare(username, quiet=False):
    token_file = os.path.join(BUDDIES_DIR, username, "share_token")
    if not os.path.exists(token_file):
        if not quiet:
            print(f"{username} has no active link.")
        return
    token = open(token_file).read().strip()
    if token:
        shutil.rmtree(os.path.join(WEB_ROOT, "join", token), ignore_errors=True)
    os.remove(token_file)
    if not quiet:
        print(f"Link for {username} taken down.")


STYLE = PAGE.template.split("<style>")[1].split("</style>")[0]

DRONE_PAGE = string.Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Drone video setup</title>
<style>$style
  textarea { width:100%; font:14px/1.4 ui-monospace, monospace; padding:10px; border-radius:8px;
             border:1px solid var(--line); background:var(--bg); color:var(--ink); resize:none; }
  button.btn { border:0; cursor:pointer; font-size:1rem; }
</style>
</head>
<body>
<main>
  <h1>Drone video: $name</h1>
  <p class="sub">Streams this drone's camera to $team. Open this page on the phone or controller
  that runs DJI Fly.</p>

  <div class="card mine">
    <h2>1. Copy the stream address</h2>
    <textarea id="url" rows="4" readonly>$url</textarea>
    <button class="btn" onclick="copyUrl(this)">Copy address</button>
  </div>

  <div class="card">
    <h2>2. Start streaming in DJI Fly</h2>
    <ol>
      <li>Power on the drone and open the camera view in DJI Fly.</li>
      <li>Tap <b>&middot;&middot;&middot;</b> (top right) &rarr; <b>Transmission</b> &rarr;
          <b>Live Streaming Platforms</b> &rarr; <b>RTMP</b>.</li>
      <li>Paste the address and start the stream.</li>
    </ol>
    <p>The phone or controller needs mobile data or Wi-Fi while streaming. Controllers with a
    built-in screen (DJI RC, RC 2) only offer RTMP on some drones, after a firmware update.</p>
  </div>

  <div class="card">
    <h2>3. The team watches</h2>
    <p>The stream appears as <b>$name</b>: in ATAK under <b>Video Player</b> (tap the download
    button, then enter your own username and password on the stream), and on the web map under
    <b>Video Streams</b>.</p>
  </div>

  <p class="sub">This address includes the drone's own login, and RTMP isn't encrypted, so keep it
  private. If it leaks, the server admin runs <code>takcx disable $name</code>.</p>
</main>
<script>
  function copyUrl(b) {
    var t = document.getElementById("url"); t.select();
    (navigator.clipboard ? navigator.clipboard.writeText(t.value) : Promise.reject())
      .catch(function () { document.execCommand("copy"); });
    b.textContent = "Copied";
  }
</script>
</body>
</html>
""")


def drone_url(team, username, password):
    return (f"rtmp://{team['SERVER_ADDRESS']}:1935/{username}"
            f"?user={urllib.parse.quote(username)}&pass={urllib.parse.quote(password)}")


def write_drone_page(team, username, profile):
    out = os.path.join(BUDDIES_DIR, username)
    os.makedirs(out, mode=0o700, exist_ok=True)
    url = drone_url(team, username, profile["password"])
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(DRONE_PAGE.substitute(style=STYLE, name=html.escape(username),
                                      team=html.escape(team["TEAM_NAME"]), url=html.escape(url)))
    fd = os.open(os.path.join(out, "profile.json"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(profile, f, indent=2)
    return url


def cmd_add_drone(args):
    team = load_team()
    username = check_username(args.name)
    ots = connect(team)
    if ots.find_user(username):
        raise TakcxError(f"{username} already exists. Pick another name, or `takcx remove {username}`.")
    password = new_password()
    ots.call("POST", "/api/user/add", {"username": username, "password": password,
                                        "confirm_password": password, "roles": ["user"]})
    profile = {"type": "drone", "callsign": username, "password": password,
               "created": datetime.now().isoformat(timespec="seconds")}
    url = write_drone_page(team, username, profile)
    print(f"\nDrone login {username} is ready. Stream address for DJI Fly "
          f"(Transmission -> Live Streaming Platforms -> RTMP):\n\n  {url}\n")
    print_qr(url)
    if not team_flag("VIDEO_ENABLED"):
        print("Note: live video isn't switched on yet. Run setup/enable-video.sh first.")
    if args.share:
        do_share(team, username)
    else:
        print(f"Easiest way to get it onto the drone's phone: takcx share {username}")


def cmd_share(args):
    do_share(load_team(), check_username(args.name))


def cmd_unshare(args):
    unshare(check_username(args.name))


def cmd_maps(args):
    team = load_team()
    os.makedirs(TAKCX_HOME, exist_ok=True)
    path = os.path.join(TAKCX_HOME, f"{slug(team['TEAM_NAME'])}-maps.zip")
    count = build_maps_zip(team, path)
    print(f"Built {path} with {count} map sources. It has no login in it, so it's fine to\n"
          "share with anyone, including people using ATAK without the server.")


def geocode(place):
    """'40.7,-74.0' or a place name (looked up on OpenStreetMap) -> (lat, lon, label)."""
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", place)
    if m:
        return float(m.group(1)), float(m.group(2)), place.strip()
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=1&q="
           + urllib.parse.quote(place))
    req = urllib.request.Request(url, headers={"User-Agent": "ATAK-CX takcx (aircraft setup)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            results = json.load(r)
    except OSError as e:
        raise TakcxError(f"Couldn't look up '{place}' ({e}). Give coordinates instead, e.g. 39.74,-104.99")
    if not results:
        raise TakcxError(f"Couldn't find '{place}'. Try a nearby town, or coordinates like 39.74,-104.99")
    return float(results[0]["lat"]), float(results[0]["lon"]), results[0]["display_name"]


def cmd_aircraft(args):
    team = load_team()
    conf_path = os.path.join(TAKCX_HOME, "team.conf")
    if args.action == "off":
        connect(team).call("POST", "/api/scheduler/job/pause", {"job_id": "get_adsb_data"})
        write_shell_conf_value(conf_path, "AIRCRAFT_ENABLED", "no")
        print("Aircraft tracking is off.")
        return

    if args.action == "on":
        if args.near:
            lat, lon, label = geocode(args.near)
        elif team.get("AIRCRAFT_LAT") and team.get("AIRCRAFT_LON"):
            lat, lon, label = float(team["AIRCRAFT_LAT"]), float(team["AIRCRAFT_LON"]), \
                team.get("AIRCRAFT_NEAR", "")
        else:
            raise TakcxError('Where should it look? e.g. takcx aircraft on --near "Denver, CO"')
        radius = args.radius or int(team.get("AIRCRAFT_RADIUS_NM") or 50)
        if not 1 <= radius <= 250:
            raise TakcxError("--radius is in nautical miles, 1 to 250.")
        print(f"Tracking aircraft within {radius} nm of {label} ({lat:.4f}, {lon:.4f})")
        changed = set_ots_config({"OTS_ADSB_LAT": round(lat, 5), "OTS_ADSB_LON": round(lon, 5),
                                  "OTS_ADSB_RADIUS": radius, "OTS_ADSB_API_URL": ADSB_API_URL})
        if changed:
            restart_ots()
        for key, value in (("AIRCRAFT_ENABLED", "yes"), ("AIRCRAFT_NEAR", label.replace('"', "")),
                           ("AIRCRAFT_LAT", round(lat, 5)), ("AIRCRAFT_LON", round(lon, 5)),
                           ("AIRCRAFT_RADIUS_NM", radius)):
            write_shell_conf_value(conf_path, key, value)
        ots = connect(team)
        ots.call("POST", "/api/scheduler/job/modify",
                 {"job_id": "get_adsb_data", "trigger": "interval", "seconds": 30})
        ots.call("POST", "/api/scheduler/job/resume", {"job_id": "get_adsb_data"})
    else:  # sync
        if not team_flag("AIRCRAFT_ENABLED"):
            raise TakcxError('Aircraft tracking is off. Turn it on with: takcx aircraft on --near "Town"')
        ots = connect(team)

    count = 0
    for user in ots.users():
        profile = load_profile(user["username"]) or {}
        if profile.get("type") != "drone":
            join_aircraft_groups(ots, user["username"])
            count += 1
    if args.action == "on":
        ots.call("POST", "/api/scheduler/job/run", {"job_id": "get_adsb_data"})
    print(f"Done. {count} accounts will see aircraft (updated every 30 s). Anyone connected "
          "may need to reconnect once (toggle the server off/on in ATAK) to start seeing them.")


def apk_info(path):
    """Read an APK with OpenTAKServer's own Python (it ships androguard)."""
    script = (
        "import sys, logging\n"
        "logging.disable(logging.CRITICAL)\n"
        "try:\n"
        "    from loguru import logger; logger.remove()\n"
        "except Exception:\n"
        "    pass\n"
        "from androguard.core.apk import APK\n"
        "a = APK(sys.argv[1])\n"
        "ns = '{http://schemas.android.com/apk/res/android}'\n"
        "api = ''\n"
        "for m in a.get_android_manifest_xml().iter('meta-data'):\n"
        "    if m.get(ns + 'name') == 'plugin-api':\n"
        "        api = m.get(ns + 'value') or ''\n"
        "import json\n"
        "print('TAKCX' + json.dumps({'package': a.get_package(), 'name': a.get_app_name(),\n"
        "                            'version': a.get_androidversion_name(), 'plugin_api': api}))\n")
    if not os.path.exists(OTS_PYTHON):
        return None
    r = subprocess.run([OTS_PYTHON, "-c", script, path], capture_output=True, text=True)
    found = [line[5:] for line in r.stdout.splitlines() if line.startswith("TAKCX")]
    if r.returncode != 0 or not found:
        last = (r.stderr.strip().splitlines() or ["unknown error"])[-1]
        raise TakcxError(f"{path} doesn't look like a valid APK ({last[-200:]})")
    return json.loads(found[-1])


def cmd_plugin(args):
    team = load_team()
    ots = connect(team)
    if args.action == "list":
        data = ots.call("GET", "/api/packages?per_page=100")
        rows = data.get("results", [])
        if not rows:
            print("No plugins on the server yet. Add one with: takcx plugin upload FILE.apk")
        for pkg in rows:
            print(f"{pkg.get('name') or pkg.get('package_name')}  v{pkg.get('version')}  "
                  f"[{pkg.get('package_name')}]  for ATAK {pkg.get('atak_version') or pkg.get('tak_prereq') or 'any'}")
        return

    if args.action == "remove":
        if not args.target:
            raise TakcxError("Which plugin? Give its package name from `takcx plugin list`.")
        query = "package_name=" + urllib.parse.quote(args.target)
        if args.atak_version:
            query += "&atak_version=" + urllib.parse.quote(args.atak_version)
        ots.call("DELETE", f"/api/packages?{query}")
        print(f"Removed {args.target}.")
        return

    if not args.target:
        raise TakcxError("Which APK? e.g. takcx plugin upload ~/Downloads/plugin.apk")
    path = os.path.expanduser(args.target)
    if not path.lower().endswith(".apk") or not os.path.isfile(path):
        raise TakcxError(f"{args.target} isn't an .apk file.")
    info = apk_info(path)
    atak_version = args.atak_version
    if info:
        print(f"{info['name']} {info['version']} ({info['package']}), built for {info['plugin_api'] or 'unknown ATAK'}")
        if not info["plugin_api"]:
            print("Warning: this doesn't look like an ATAK plugin (no plugin-api tag). Uploading anyway.")
        m = re.search(r"@(\d+)\.(\d+)\.(\d+)", info["plugin_api"])
        # ATAK 5.5+ asks the server for plugins matching its own version.
        if not atak_version and m and (int(m.group(1)), int(m.group(2))) >= (5, 5):
            atak_version = ".".join(m.groups())
    fields = {"platform": "Android", "plugin_type": "plugin",
              "install_on_enrollment": "false", "install_on_connection": "false"}
    if atak_version:
        fields["atak_version"] = atak_version
    print("Uploading...")
    ots.upload("/api/packages", fields, "apk", path)
    print(f"Done. Everyone's ATAK{' ' + atak_version if atak_version else ''} offers it the next time "
          "ATAK starts (or in the Plugins tool, tap sync).")


def cmd_doctor(args):
    ok = True

    def report(good, label, hint=""):
        nonlocal ok
        ok = ok and good
        print(f"  [{'ok' if good else '!!'}] {label}" + ("" if good or not hint else f"\n       -> {hint}"))

    radio = radio_enabled()
    video = team_flag("VIDEO_ENABLED")
    alerts = team_flag("ALERTS_ENABLED")
    print("Services")
    for svc in (SERVICES + (["mumble-server"] if radio else []) + (["mediamtx"] if video else [])
                + (["takcx-alerts"] if alerts else [])):
        state = subprocess.run(["systemctl", "is-active", svc], capture_output=True,
                               text=True).stdout.strip() if shutil.which("systemctl") else "unknown"
        report(state == "active", f"{svc}: {state or 'not running'}", f"sudo systemctl restart {svc}; "
               f"logs: journalctl -u {svc} -n 50 (OTS logs: ~/ots/logs/opentakserver.log)")

    print("OpenTAKServer")
    try:
        with urllib.request.urlopen(f"http://{OTS_API}/api/health", timeout=5) as r:
            report(r.status == 200, "API is healthy")
    except OSError as e:
        report(False, f"API not reachable at {OTS_API}: {e}", "sudo systemctl restart opentakserver")

    try:
        team = load_team()
        admin_ok = True
        try:
            connect(team)
        except TakcxError as e:
            admin_ok = False
            report(False, f"admin login: {e}")
        if admin_ok:
            report(True, "admin login works")
    except TakcxError as e:
        report(False, str(e))
        return 1

    print("Network")
    address = team["SERVER_ADDRESS"]
    try:
        resolved = socket.gethostbyname(address)
        report(True, f"{address} resolves to {resolved}")
    except OSError:
        resolved = None
        report(False, f"{address} doesn't resolve", "check your DNS / DuckDNS record")
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
            public_ip = r.read().decode().strip()
        if resolved and not resolved.startswith(("10.", "192.168.", "172.")) \
                and not re.match(r"^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.", resolved):
            report(resolved == public_ip, f"this server's public IP is {public_ip}",
                   f"{address} points at {resolved}, not this server. Fix the DNS record.")
    except OSError:
        print("  [--] couldn't look up public IP (no internet?)")
    if shutil.which("ss"):
        listening = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True).stdout
        ports = [("443", "web map / share links", "nginx"),
                 ("8089", "TAK clients (TLS)", "eud_handler_ssl"),
                 ("8443", "TAK API (data packages)", "nginx"),
                 ("8446", "certificate enrollment", "nginx")]
        if radio:
            ports.append(("64738", "team radio", "mumble-server"))
        if video:
            ports += [("1935", "drone/RTMP video in", "mediamtx"), ("8554", "video to ATAK (RTSP)", "mediamtx")]
        for port, what, svc in ports:
            report(f":{port} " in listening, f"port {port} listening ({what})",
                   f"sudo systemctl restart {svc}")
    if shutil.which("ufw"):
        status = subprocess.run(["sudo", "-n", "ufw", "status"], capture_output=True,
                                text=True).stdout
        if "Status: active" in status:
            for port in (("8089", "8443", "8446") + (("64738",) if radio else ())
                         + (("1935", "8554") if video else ())):
                report(port in status, f"firewall allows {port}", f"sudo ufw allow {port}")
    if radio:
        print("Radio")
        linked = radio_link_state()
        if linked is None:
            print("  [--] couldn't read Mumble's log to check the login link")
        else:
            report(linked, "radio logins linked to takcx accounts",
                   "nobody can join the radio until this is fixed: sudo systemctl restart mumble-server")
    if team_flag("AIRCRAFT_ENABLED"):
        print("Aircraft")
        try:
            jobs = connect(team).call("GET", "/api/scheduler/jobs")
            job = next((j for j in jobs if j.get("id") == "get_adsb_data"), {})
            report(bool(job.get("next_run_time")), "aircraft updates running",
                   'takcx aircraft on   (re-activates the job)')
        except TakcxError as e:
            report(False, f"couldn't check aircraft job: {e}")
    extra = (" 64738 (TCP+UDP)" if radio else "") + (" 1935 8554" if video else "")
    print("\nRemember: a cloud provider firewall or home router also has to let ports\n"
          "443 8089 8443 8446" + extra + " through. See docs/troubleshooting.md.")
    print("\nAll good." if ok else "\nSome checks failed; see the hints above.")
    return 0 if ok else 1


def cmd_admin_password(args):
    """Used by install-server.sh: rotate the default OTS admin password."""
    team = load_team()
    admin_path = os.path.join(TAKCX_HOME, "admin.conf")
    admin = read_shell_conf(admin_path)
    current = admin.get("OTS_ADMIN_PASSWORD") or "password"
    user = admin.get("OTS_ADMIN_USER", "administrator")
    ots = OTS(team["SERVER_ADDRESS"])
    ots.login(user, current)
    new = args.password or new_password(20)
    ots.call("POST", "/api/user/password/reset", {"username": user, "new_password": new})
    os.makedirs(TAKCX_HOME, exist_ok=True)
    with open(admin_path, "w") as f:
        f.write(f'OTS_ADMIN_USER="{user}"\nOTS_ADMIN_PASSWORD="{new}"\n')
    os.chmod(admin_path, 0o600)
    print(f"Web admin login: {user} / {new}\n(saved in {admin_path})")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="takcx", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="add a buddy")
    p.add_argument("name", help="username, e.g. bob (lowercase letters, numbers, _ or .)")
    p.add_argument("--callsign", help="name shown on the map (default: the username)")
    p.add_argument("--color", help="team color, e.g. Cyan, Red, Green")
    p.add_argument("--role", help='role, e.g. "Team Lead", Medic, HQ')
    p.add_argument("--admin", action="store_true", help="also make them a server admin")
    p.add_argument("--share", action="store_true", help="publish a private download link")
    p.add_argument("--no-web-login", action="store_true",
                   help="leave the web map password off their how-to page")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("rebuild", help="rebuild packages after changing team.conf or maps/")
    p.add_argument("names", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--callsign")
    p.add_argument("--color")
    p.add_argument("--role")
    p.set_defaults(func=cmd_rebuild)

    sub.add_parser("list", help="list everyone").set_defaults(func=cmd_list)
    for name, func, text in (("enable", cmd_enable, "restore someone's access"),
                             ("share", cmd_share, "publish a private download link"),
                             ("unshare", cmd_unshare, "take a download link down")):
        p = sub.add_parser(name, help=text)
        p.add_argument("name")
        p.set_defaults(func=func)
    p = sub.add_parser("disable", help="cut off someone's access")
    p.add_argument("name")
    p.add_argument("--no-kick", action="store_true", help="don't drop live connections")
    p.set_defaults(func=cmd_disable)
    p = sub.add_parser("remove", help="delete someone for good")
    p.add_argument("name")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    p.add_argument("--no-kick", action="store_true", help="don't drop live connections")
    p.set_defaults(func=cmd_remove)
    sub.add_parser("maps", help="build a maps-only package").set_defaults(func=cmd_maps)
    p = sub.add_parser("add-drone", help="a login + stream address for a drone (DJI Fly RTMP)")
    p.add_argument("name", help="e.g. drone1 (this is also the stream's name)")
    p.add_argument("--share", action="store_true", help="publish a private setup page")
    p.set_defaults(func=cmd_add_drone)
    p = sub.add_parser("aircraft", help="live aircraft (ADS-B) on everyone's map")
    p.add_argument("action", choices=["on", "off", "sync"],
                   help="on: start (or change area); off: stop; sync: re-add everyone to the aircraft feed")
    p.add_argument("--near", help='town or "lat,lon" to center on, e.g. "Denver, CO"')
    p.add_argument("--radius", type=int, help="nautical miles around it, max 250 (default 50)")
    p.set_defaults(func=cmd_aircraft)
    p = sub.add_parser("plugin", help="push ATAK plugins to everyone")
    p.add_argument("action", choices=["upload", "list", "remove"])
    p.add_argument("target", nargs="?", help="APK file (upload) or package name (remove)")
    p.add_argument("--atak-version", help="ATAK version it's for, e.g. 5.5.0 (read from the APK if left out)")
    p.set_defaults(func=cmd_plugin)
    sub.add_parser("doctor", help="check the server").set_defaults(func=cmd_doctor)
    p = sub.add_parser("admin-password", help="set a new random web admin password")
    p.add_argument("--password", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_admin_password)

    args = parser.parse_args(argv)
    os.makedirs(BUDDIES_DIR, exist_ok=True)
    for private in (TAKCX_HOME, BUDDIES_DIR):
        os.chmod(private, 0o700)
    try:
        return args.func(args) or 0
    except TakcxError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

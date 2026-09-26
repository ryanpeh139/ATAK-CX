#!/usr/bin/env python3
"""Update OpenTAKServer (the server and its web map) without losing ATAK-CX's files.

OpenTAKServer's own upgrader empties the web map's folder, which also holds everyone's
private links (join/) and downloads like elevation data (files/). This keeps those,
backs up first, never asks questions, and only restarts services, so the Manager can
run it as well as you over SSH.

  ots_update.py --check    say what's installed and what's available
  ots_update.py            update whatever is out of date

Run it with OpenTAKServer's Python (setup/update.sh does).
"""

import importlib.metadata
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

REPO_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
WEB_ROOT = os.environ.get("TAKCX_WEB_ROOT", "/var/www/html/opentakserver")
VENV_BIN = os.path.dirname(sys.executable)
UI_REPO = "https://github.com/brian7704/OpenTAKServer-UI"
UI_VERSION_FILE = os.path.join(WEB_ROOT, ".takcx-ui-version")
KEEP = {"join", "files", "takcx"}  # ATAK-CX's own folders in the web map's folder
HEALTH_URL = "http://127.0.0.1:8081/api/health"


class UpdateError(Exception):
    pass


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "ATAK-CX updater"})
    return urllib.request.urlopen(req, timeout=timeout)


def version_key(v):
    return [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v.lstrip("v"))]


def installed_server():
    try:
        return importlib.metadata.version("opentakserver")
    except importlib.metadata.PackageNotFoundError:
        return None


def latest_server(timeout=20):
    with fetch("https://pypi.org/pypi/opentakserver/json", timeout) as r:
        return json.load(r)["info"]["version"]


def installed_ui():
    try:
        return open(UI_VERSION_FILE).read().strip() or None
    except OSError:
        return None


def latest_ui(timeout=20):
    """The newest web map release tag, from where GitHub's "latest" link redirects to
    (no API, so no rate limit)."""
    with fetch(f"{UI_REPO}/releases/latest", timeout) as r:
        m = re.search(r"/releases/tag/([^/?#]+)$", r.geturl())
    if not m:
        raise UpdateError("Couldn't find the latest web map release on GitHub.")
    return urllib.request.unquote(m.group(1))


def status(timeout=20):
    out = {"server": installed_server(), "ui": installed_ui(), "server_latest": None, "ui_latest": None}
    try:
        out["server_latest"] = latest_server(timeout)
    except Exception:  # offline, PyPI down...
        pass
    try:
        out["ui_latest"] = latest_ui(timeout)
    except Exception:
        pass
    out["server_behind"] = bool(out["server"] and out["server_latest"]
                                and version_key(out["server_latest"]) > version_key(out["server"]))
    out["ui_behind"] = bool(out["ui_latest"] and out["ui_latest"] != out["ui"])
    return out


def run(cmd, **kw):
    print("$ " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        raise UpdateError(f"{cmd[0]} failed (exit {r.returncode}).")


def sudo(*args):
    # From the Manager there's no terminal, so never wait for a password.
    return ["sudo"] + ([] if sys.stdin.isatty() else ["-n"]) + list(args)


def wait_healthy(seconds=150):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with fetch(HEALTH_URL, 5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def update_server(old, new):
    print(f"Updating OpenTAKServer {old} -> {new}", flush=True)
    run([os.path.join(VENV_BIN, "pip"), "install", "--upgrade", "--quiet", f"opentakserver=={new}"])
    pkg = os.path.dirname(importlib.util.find_spec("opentakserver").origin)
    print("Upgrading the database...", flush=True)
    run([os.path.join(VENV_BIN, "flask"), "db", "upgrade"], cwd=pkg)


def update_ui(tag):
    if not os.path.isfile(os.path.join(WEB_ROOT, "index.html")):
        raise UpdateError(f"{WEB_ROOT} doesn't look like the web map's folder; not touching it.")
    url = f"{UI_REPO}/releases/download/{tag}/OpenTAKServer-UI-{tag}.zip"
    print(f"Downloading web map {tag}...", flush=True)
    with fetch(url, 120) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        top = {n.split("/", 1)[0] for n in names}
        strip = top.pop() + "/" if len(top) == 1 and all("/" in n for n in names) else ""
        if strip + "index.html" not in names:
            raise UpdateError("That download doesn't contain a web map (no index.html). Nothing changed.")
        staging = tempfile.mkdtemp(prefix="takcx-ui-")
        try:
            for n in names:
                rel = n[len(strip):]
                dest = os.path.realpath(os.path.join(staging, rel))
                if not rel or not dest.startswith(os.path.realpath(staging) + os.sep):
                    continue  # skip anything that would land outside
                if rel.split("/", 1)[0] in KEEP:
                    continue  # never let a download overwrite links or downloads
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(n) as src, open(dest, "wb") as f:
                    shutil.copyfileobj(src, f)
            # Swap: remove the old web map (keeping our folders and dotfiles), move the new one in.
            for entry in os.listdir(WEB_ROOT):
                if entry in KEEP or entry.startswith("."):
                    continue
                path = os.path.join(WEB_ROOT, entry)
                shutil.rmtree(path) if os.path.isdir(path) and not os.path.islink(path) else os.remove(path)
            for entry in os.listdir(staging):
                shutil.move(os.path.join(staging, entry), os.path.join(WEB_ROOT, entry))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    with open(UI_VERSION_FILE, "w") as f:
        f.write(tag + "\n")
    print(f"Web map is now {tag}. Your private links and downloads were kept.", flush=True)
    conf = os.path.join(os.environ.get("TAKCX_HOME", os.path.expanduser("~/takcx")), "team.conf")
    if os.path.exists(conf) and re.search(r'^WEBMAP_THEME="?yes', open(conf).read(), re.M):
        r = subprocess.run([sys.executable, os.path.join(REPO_DIR, "takcx", "takcx.py"), "webmap-theme", "on"])
        if r.returncode != 0:
            print("(Couldn't re-apply the team look to the web map; run: takcx webmap-theme on)", flush=True)


def rollback_help(old):
    return (f"\nTo go back to {old}:\n"
            f"  ~/.opentakserver_venv/bin/pip install opentakserver=={old}\n"
            "  restore the database from the backup made just now (see docs/maintenance.md)\n"
            "  sudo systemctl restart opentakserver")


def main():
    check = "--check" in sys.argv[1:]
    s = status()
    print(f"OpenTAKServer: {s['server'] or 'not found'}"
          + (f" (newest: {s['server_latest']})" if s["server_latest"] else " (couldn't check PyPI)"))
    print(f"Web map:       {s['ui'] or 'unknown'}"
          + (f" (newest: {s['ui_latest']})" if s["ui_latest"] else " (couldn't check GitHub)"))
    if check:
        print(json.dumps(s))
        return 0
    if not s["server"]:
        raise UpdateError("OpenTAKServer isn't installed in this Python. Run this with "
                          "~/.opentakserver_venv/bin/python.")
    if not s["server_behind"] and not s["ui_behind"]:
        print("OpenTAKServer and the web map are up to date.")
        return 0

    print("Backing up first...", flush=True)
    run([os.path.join(REPO_DIR, "setup", "backup.sh")])

    if s["server_behind"]:
        try:
            update_server(s["server"], s["server_latest"])
        except UpdateError as e:
            raise UpdateError(f"{e}{rollback_help(s['server'])}")
        print("Restarting OpenTAKServer (apps reconnect on their own)...", flush=True)
        for svc in (["opentakserver"], ["cot_parser"], ["eud_handler_ssl", "eud_handler"]):
            run(sudo("systemctl", "restart", *svc))
        if not wait_healthy():
            raise UpdateError("OpenTAKServer didn't come back after the update. "
                              "Check ~/ots/logs/opentakserver.log." + rollback_help(s["server"]))
        print(f"OpenTAKServer {s['server_latest']} is running.", flush=True)

    if s["ui_behind"]:
        update_ui(s["ui_latest"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except UpdateError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

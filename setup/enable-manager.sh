#!/usr/bin/env bash
# ATAK-CX Manager: a web dashboard at https://<server>/manage/ for adding people,
# drones, plugins, changing settings, add-ons and backups.
#
#   ./setup/enable-manager.sh        (install-server.sh offers to run this)
#
# Log in with an OpenTAKServer administrator account. Make your own with
#   takcx add yourname --admin
# and turn on two-factor login for it in the web map (see docs/8-manager.md).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
TEAM_CONF="$TAKCX_HOME/team.conf"
OTS_PY="$HOME/.opentakserver_venv/bin/python"
SITE=/etc/nginx/sites-available/ots_https
ME="$(whoami)"

die() { echo "Error: $*" >&2; exit 1; }

[[ $EUID -ne 0 ]] || die "Run this as the same (non-root) user you ran install-server.sh as."
[[ -f $TEAM_CONF ]] || die "No $TEAM_CONF. Run setup/install-server.sh first."
[[ -x $OTS_PY ]] || die "OpenTAKServer isn't installed for this user."
"$OTS_PY" -c "import flask" 2>/dev/null || die "OpenTAKServer's Python is missing Flask."
[[ -f $SITE ]] || die "OpenTAKServer's nginx site ($SITE) isn't there."
# shellcheck disable=SC1090
. "$TEAM_CONF"

# The manager may restart these services and read these logs, and nothing else.
# (Turning add-ons on still happens over SSH, where you type your own password.)
tmp="$(mktemp)"
cat > "$tmp" <<EOF
# ATAK-CX Manager (setup/enable-manager.sh): exactly these commands, no password.
$ME ALL=(root) NOPASSWD: /usr/bin/systemctl restart eud_handler_ssl eud_handler, \\
  /usr/bin/systemctl restart eud_handler_ssl eud_handler mumble-server, \\
  /usr/bin/systemctl restart opentakserver, \\
  /usr/bin/systemctl restart cot_parser, \\
  /usr/bin/systemctl restart eud_handler_ssl, \\
  /usr/bin/systemctl restart eud_handler, \\
  /usr/bin/systemctl restart mumble-server, \\
  /usr/bin/systemctl restart mediamtx, \\
  /usr/bin/systemctl restart takcx-alerts, \\
  /usr/bin/systemctl restart takcx-tiles, \\
  /usr/bin/systemctl restart takcx-manager, \\
  /usr/bin/systemctl restart nginx, \\
  /usr/sbin/ufw status, \\
  /usr/bin/journalctl -u mumble-server -n 300 --no-pager, \\
  /usr/bin/tail -n 300 /var/log/mumble-server/mumble-server.log
EOF
sudo visudo -cf "$tmp" >/dev/null || die "Generated sudoers rules didn't validate."
sudo install -m 0440 -o root -g root "$tmp" /etc/sudoers.d/takcx-manager
rm -f "$tmp"

sudo tee /etc/systemd/system/takcx-manager.service >/dev/null <<EOF
[Unit]
Description=ATAK-CX Manager (web dashboard)
After=network-online.target opentakserver.service

[Service]
User=$ME
Environment=TAKCX_HOME=$TAKCX_HOME
ExecStart=$OTS_PY $REPO_DIR/takcx/manager/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable takcx-manager >/dev/null 2>&1
sudo systemctl restart takcx-manager

sudo python3 "$REPO_DIR/setup/nginx_add_location.py" "$SITE" /manage/ 8096 300M
sudo nginx -t
sudo systemctl reload nginx

echo -n "Checking"
for _ in $(seq 1 10); do
  sleep 2; echo -n "."
  if curl -fsk -o /dev/null --max-time 10 "https://127.0.0.1/manage/login"; then
    echo
    sed -i 's/^MANAGER_ENABLED=.*/MANAGER_ENABLED="yes"/' "$TEAM_CONF"
    grep -q '^MANAGER_ENABLED=' "$TEAM_CONF" || echo 'MANAGER_ENABLED="yes"' >> "$TEAM_CONF"
    # One login and one look for the Manager and the web map (undo: takcx webmap-theme off).
    if ! grep -q '^WEBMAP_THEME="no"' "$TEAM_CONF"; then
      "$OTS_PY" "$REPO_DIR/takcx/takcx.py" webmap-theme on >/dev/null && echo "The web map now shares the Manager's look and login."
    fi
    cat <<EOF

The Manager is at: https://${SERVER_ADDRESS:-your-server}/manage/
Log in with an OpenTAKServer admin account. Make your own (and use it instead of
the built-in "administrator", which takcx needs for itself):
  takcx add yourname --admin --share
Then turn on two-factor login for it: docs/8-manager.md
EOF
    exit 0
  fi
done
echo
die "The Manager isn't answering. Check: journalctl -u takcx-manager -n 30"

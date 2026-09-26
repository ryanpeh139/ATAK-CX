#!/usr/bin/env bash
# Emergency alerts to phones: when anyone triggers an emergency in ATAK
# (911 Alert, Ring The Bell, Troops In Contact...), everyone subscribed gets a
# push notification with a map link, even with ATAK closed. Uses the free ntfy
# app; Discord and Telegram are optional extras.
#
#   ./setup/enable-alerts.sh        (install-server.sh offers to run this)
#
# Re-run it to add or change Discord/Telegram. The ntfy topic stays the same.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
TEAM_CONF="$TAKCX_HOME/team.conf"
OTS_PY="$HOME/.opentakserver_venv/bin/python"

die() { echo "Error: $*" >&2; exit 1; }
ask() {  # arrow keys and control characters are stripped from answers
  local a; read -r -e -p "$1: " a < /dev/tty || true
  printf '%s' "$a" | sed $'s/\e\[[0-9;]*[A-Za-z]//g' | tr -cd '[:print:]' | sed 's/^ *//;s/ *$//'
}
set_conf() {  # set_conf KEY VALUE
  local tmp; tmp="$(mktemp)"
  grep -v "^$1=" "$TEAM_CONF" > "$tmp" || true
  printf '%s="%s"\n' "$1" "${2//\"/}" >> "$tmp"
  cat "$tmp" > "$TEAM_CONF"; rm -f "$tmp"
}

[[ $EUID -ne 0 ]] || die "Run this as the same (non-root) user you ran install-server.sh as."
[[ -f $TEAM_CONF ]] || die "No $TEAM_CONF. Run setup/install-server.sh first."
[[ -x $OTS_PY ]] || die "OpenTAKServer isn't installed for this user."
# shellcheck disable=SC1090
. "$TEAM_CONF"

if [[ -z ${NTFY_TOPIC:-} ]]; then
  # The topic name is the only "password" on ntfy.sh, so make it unguessable.
  slug="$(echo "${TEAM_NAME:-team}" | tr -cs 'A-Za-z0-9' '-' | tr '[:upper:]' '[:lower:]' | sed 's/^-*//;s/-*$//')"
  NTFY_TOPIC="${slug:-team}-alerts-$(openssl rand -hex 8)"
  set_conf NTFY_TOPIC "$NTFY_TOPIC"
fi
NTFY_SERVER="${NTFY_SERVER:-https://ntfy.sh}"

echo "Optional extras (press Enter to skip each):"
discord="$(ask "  Discord webhook URL (Server Settings -> Integrations -> Webhooks)")"
[[ -n $discord ]] && set_conf DISCORD_WEBHOOK "$discord"
tg_token="$(ask "  Telegram bot token (from @BotFather)")"
if [[ -n $tg_token ]]; then
  tg_chat="$(ask "  Telegram chat ID (add the bot to your group; see docs/7-alerts.md)")"
  set_conf TELEGRAM_BOT_TOKEN "$tg_token"
  [[ -n $tg_chat ]] && set_conf TELEGRAM_CHAT_ID "$tg_chat"
fi
set_conf ALERTS_ENABLED yes

sudo tee /etc/systemd/system/takcx-alerts.service >/dev/null <<EOF
[Unit]
Description=ATAK-CX emergency alerts to phones
Wants=rabbitmq-server.service
After=network-online.target rabbitmq-server.service opentakserver.service

[Service]
User=$(whoami)
Environment=TAKCX_HOME=$TAKCX_HOME
ExecStart=$OTS_PY $REPO_DIR/takcx/alert_bridge.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable takcx-alerts >/dev/null 2>&1
sudo systemctl restart takcx-alerts

echo
echo "Sending a test notification..."
TAKCX_HOME="$TAKCX_HOME" "$OTS_PY" "$REPO_DIR/takcx/alert_bridge.py" --test || true

if [[ -n $(ls -A "$TAKCX_HOME/buddies" 2>/dev/null) ]]; then
  "$REPO_DIR/takcx/takcx.py" rebuild --all >/dev/null && echo "Added alert sign-up to everyone's welcome page."
fi

link="$NTFY_SERVER/$NTFY_TOPIC"
cat <<EOF

Emergency alerts are on. To get them on a phone:
  1. Install the free "ntfy" app (Play Store / App Store).
  2. Subscribe to topic:  $NTFY_TOPIC
     (or open $link on the phone)
Anyone with the topic name can read alerts, including locations, so share it only with the team.
EOF
command -v qrencode >/dev/null && qrencode -t ANSIUTF8 -m 2 "$link"

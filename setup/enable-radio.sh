#!/usr/bin/env bash
# Team radio: push-to-talk voice channels on a Mumble server, locked to the
# same accounts as the map. Disable someone with takcx and they lose the radio too.
#
#   ./setup/enable-radio.sh        (install-server.sh offers to run this)
#
# Safe to re-run, e.g. after changing RADIO_CHANNELS or TEAM_NAME in ~/takcx/team.conf.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
TEAM_CONF="$TAKCX_HOME/team.conf"
OTS_VENV="$HOME/.opentakserver_venv"
OTS_CONFIG="${OTS_DATA_FOLDER:-$HOME/ots}/config.yml"

step() { echo; echo "==> $*"; }
die()  { echo "Error: $*" >&2; exit 1; }

[[ $EUID -ne 0 ]] || die "Run this as the same (non-root) user you ran install-server.sh as."
[[ -f $TEAM_CONF ]] || die "No $TEAM_CONF. Run setup/install-server.sh first."
[[ -x $OTS_VENV/bin/python && -f $OTS_CONFIG ]] || die "OpenTAKServer isn't installed for this user."
# shellcheck disable=SC1090
. "$TEAM_CONF"
channels="${RADIO_CHANNELS:-Main,Team 1,Team 2,Command}"

step "Installing Mumble server"
sudo apt-get install -y -qq mumble-server python3-zeroc-ice zeroc-ice-slice >/dev/null
"$OTS_VENV/bin/python" -c "import Ice" 2>/dev/null \
  || die "OpenTAKServer's Python can't load Ice (python3-zeroc-ice), so it couldn't check radio logins."

ini=/etc/mumble/mumble-server.ini            # Mumble 1.5 (Debian 13 / Ubuntu 24.04)
[[ -f $ini ]] || ini=/etc/mumble-server.ini  # Mumble 1.3 (Debian 12)
[[ -f $ini ]] || die "Can't find Mumble's config file."

step "Configuring $ini"
sudo python3 "$REPO_DIR/setup/mumble_conf.py" "$ini" "${TEAM_NAME:-Team}"

step "Linking radio logins to OpenTAKServer accounts"
if grep -q '^OTS_ENABLE_MUMBLE_AUTHENTICATION:' "$OTS_CONFIG"; then
  sed -i 's/^OTS_ENABLE_MUMBLE_AUTHENTICATION:.*/OTS_ENABLE_MUMBLE_AUTHENTICATION: true/' "$OTS_CONFIG"
else
  echo 'OTS_ENABLE_MUMBLE_AUTHENTICATION: true' >> "$OTS_CONFIG"
fi

# OpenTAKServer only hooks into Mumble when it starts, so: start Mumble first,
# and restart OpenTAKServer every time Mumble (re)starts. In between, the radio
# stays locked by the random server password rather than open.
sudo mkdir -p /etc/systemd/system/opentakserver.service.d /etc/systemd/system/mumble-server.service.d
sudo tee /etc/systemd/system/opentakserver.service.d/takcx-radio.conf >/dev/null <<'EOF'
# ATAK-CX: radio logins are checked by OpenTAKServer, which needs Mumble up first.
[Unit]
Wants=mumble-server.service
After=mumble-server.service
EOF
sudo tee /etc/systemd/system/mumble-server.service.d/takcx-radio.conf >/dev/null <<'EOF'
# ATAK-CX: reconnect OpenTAKServer's login check whenever Mumble restarts.
[Service]
ExecStartPost=+/bin/sh -c 'sleep 3; systemctl --no-block try-restart opentakserver.service'
EOF
sudo systemctl daemon-reload
sudo systemctl enable mumble-server >/dev/null 2>&1
sudo systemctl restart mumble-server

step "Creating channels"
IFS=',' read -ra channel_list <<< "$channels"
"$OTS_VENV/bin/python" "$REPO_DIR/setup/radio_channels.py" "${channel_list[@]}"
# The start channel is read when Mumble boots; this restart also restarts OpenTAKServer.
sudo systemctl restart mumble-server

if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow 64738 comment "ATAK-CX radio" >/dev/null
  echo "Firewall: opened port 64738 (TCP+UDP)."
fi

step "Checking"
echo -n "Waiting for OpenTAKServer to reconnect"
linked=no
for _ in $(seq 1 40); do
  sleep 3; echo -n "."
  if sudo journalctl -u mumble-server --since "-2 min" 2>/dev/null | grep -q "Set Ice Authenticator" \
     || sudo tail -n 30 /var/log/mumble-server/mumble-server.log 2>/dev/null | grep -q "Set Ice Authenticator"; then
    linked=yes; break
  fi
done
echo
if [[ $linked == yes ]]; then
  echo "Radio logins are linked to your takcx accounts."
else
  echo "Couldn't confirm the link yet. Nobody can get in until it's there (that's on purpose)."
  echo "Check: sudo systemctl restart opentakserver, then ~/ots/logs/opentakserver.log for 'Mumble'."
fi

sed -i 's/^RADIO_ENABLED=.*/RADIO_ENABLED="yes"/' "$TEAM_CONF"
grep -q '^RADIO_ENABLED=' "$TEAM_CONF" || echo 'RADIO_ENABLED="yes"' >> "$TEAM_CONF"
grep -q '^RADIO_CHANNELS=' "$TEAM_CONF" || echo "RADIO_CHANNELS=\"$channels\"" >> "$TEAM_CONF"

if [[ -n $(ls -A "$TAKCX_HOME/buddies" 2>/dev/null) ]]; then
  step "Adding radio instructions to everyone's welcome page"
  "$REPO_DIR/takcx/takcx.py" rebuild --all >/dev/null && echo "Done."
fi

cat <<EOF

Team radio is ready: server ${SERVER_ADDRESS:-your-server}, port 64738.
Everyone logs in with their takcx username and password (it's on their welcome page).
Apps: Mumla (Android), Mumble (Windows/Mac/iPhone). Channels: $channels
EOF

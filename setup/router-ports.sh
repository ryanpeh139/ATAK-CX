#!/usr/bin/env bash
# Home server: have your router forward ATAK-CX's ports to this machine automatically
# (UPnP), instead of typing each one into the router's app. Re-applied every 30 minutes,
# so a router reboot doesn't quietly close them.
#
#   ./setup/router-ports.sh            open the ports and keep them open
#   ./setup/router-ports.sh --list     show what the router forwards right now
#   ./setup/router-ports.sh --off      close them again and stop re-applying
#
# Needs UPnP turned on in the router (AmpliFi: on by default; others: look for "UPnP").
# Only the ports your add-ons use are opened, never SSH.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
TEAM_CONF="$TAKCX_HOME/team.conf"
DESC="ATAK-CX"
MODE="${1:-}"

die() { echo "Error: $*" >&2; exit 1; }
[[ $EUID -ne 0 ]] || die "Run this as your normal user, not root."
[[ -f $TEAM_CONF ]] || die "No $TEAM_CONF. Run setup/install-server.sh first."
# shellcheck disable=SC1090
. "$TEAM_CONF"
yes_() { [[ ${1:-no} == yes ]]; }

if ! command -v upnpc >/dev/null; then
  [[ $MODE == --refresh ]] && exit 1
  echo "Installing the UPnP tool (miniupnpc)..."
  sudo apt-get install -y -qq miniupnpc >/dev/null
fi

# The ports this setup actually uses.
PORTS=("443 TCP" "8089 TCP" "8443 TCP" "8446 TCP")
yes_ "${HTTPS_ENABLED:-no}" && PORTS=("80 TCP" "${PORTS[@]}")          # certificate renewals
yes_ "${RADIO_ENABLED:-no}" && PORTS+=("64738 TCP" "64738 UDP")
yes_ "${VIDEO_ENABLED:-no}" && PORTS+=("1935 TCP" "8554 TCP" "8189 UDP")

info="$(upnpc -s 2>&1 || true)"
if ! grep -q "ExternalIPAddress" <<<"$info"; then
  [[ $MODE == --refresh ]] && exit 1
  die "Your router didn't answer UPnP. Turn on UPnP in the router's settings, or add the
forwards by hand (docs/INSTALL.md, step 4C)."
fi
lan_ip="$(sed -n 's/^Local LAN ip address *: *//p' <<<"$info" | head -1)"
wan_ip="$(sed -n 's/^ExternalIPAddress = *//p' <<<"$info" | head -1)"

if [[ $MODE == --list ]]; then
  echo "Router's outside address: $wan_ip   This server: $lan_ip"
  upnpc -l 2>/dev/null | grep -E '^ *[0-9]+ (TCP|UDP)' || echo "(no UPnP forwards)"
  echo "Forwards you typed into the router's app aren't listed here."
  exit 0
fi

if [[ $MODE == --off ]]; then
  sudo systemctl disable --now takcx-router-ports.timer 2>/dev/null || true
  for pp in "${PORTS[@]}"; do
    read -r port proto <<<"$pp"
    if upnpc -d "$port" "$proto" >/dev/null 2>&1; then echo "Closed $port/$proto"; fi
  done
  sed -i 's/^ROUTER_UPNP=.*/ROUTER_UPNP="no"/' "$TEAM_CONF"
  exit 0
fi

# A 100.64.x.x / 10.x.x.x "outside" address means the internet provider shares one public
# address between customers (CGNAT); forwarding can't work then.
if [[ $wan_ip =~ ^(10\.|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.) ]]; then
  die "Your router's outside address is $wan_ip, a shared (CGNAT) address from your internet
provider, so nothing can reach you from outside. Ask them for a public IP, or use
ZeroTier / a cloud server (docs/1-get-a-server.md)."
fi

current="$(upnpc -l 2>/dev/null || true)"
ok=0; problems=0
for pp in "${PORTS[@]}"; do
  read -r port proto <<<"$pp"
  out="$(upnpc -e "$DESC" -a "$lan_ip" "$port" "$port" "$proto" 0 2>&1 || true)"
  if ! grep -q "is redirected to" <<<"$out"; then
    # Some routers only take time-limited forwards; the timer renews them.
    out="$(upnpc -e "$DESC" -a "$lan_ip" "$port" "$port" "$proto" 7200 2>&1 || true)"
  fi
  if grep -q "is redirected to" <<<"$out"; then
    ok=$((ok + 1))
    [[ $MODE == --refresh ]] || echo "  [ok] $port/$proto -> $lan_ip"
  elif grep -Eq "^ *[0-9]+ $proto +$port->$lan_ip:$port " <<<"$current"; then
    ok=$((ok + 1))
    [[ $MODE == --refresh ]] || echo "  [ok] $port/$proto -> $lan_ip (already)"
  else
    problems=$((problems + 1))
    reason="$(grep -o 'failed with code.*' <<<"$out" | head -1)"
    [[ $MODE == --refresh ]] || echo "  [!!] $port/$proto: router said: ${reason:-no answer}.
       If you already forward $port in the router's app, make sure it points at $lan_ip."
  fi
done
[[ $MODE == --refresh ]] && exit 0

# Keep them open: re-apply every 30 minutes and after boot.
sudo tee /etc/systemd/system/takcx-router-ports.service >/dev/null <<EOF
[Unit]
Description=ATAK-CX: keep router port forwards (UPnP) open
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$(whoami)
Environment=TAKCX_HOME=$TAKCX_HOME
ExecStart=$REPO_DIR/setup/router-ports.sh --refresh
EOF
sudo tee /etc/systemd/system/takcx-router-ports.timer >/dev/null <<EOF
[Unit]
Description=ATAK-CX: re-apply router port forwards every 30 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now takcx-router-ports.timer >/dev/null 2>&1
if grep -q '^ROUTER_UPNP=' "$TEAM_CONF"; then
  sed -i 's/^ROUTER_UPNP=.*/ROUTER_UPNP="yes"/' "$TEAM_CONF"
else
  echo 'ROUTER_UPNP="yes"' >> "$TEAM_CONF"
fi

echo
echo "$ok port(s) forwarded to this server ($lan_ip); re-checked every 30 minutes."
[[ $problems -eq 0 ]] || echo "$problems couldn't be opened; see above."
cat <<EOF

Test it from OUTSIDE your network (a phone on mobile data, Wi-Fi off):
  - ATAK should connect (green server icon) within a minute.
  - Or open https://portchecker.co , enter ${SERVER_ADDRESS:-your address} and port 8089: it should say "open".
EOF

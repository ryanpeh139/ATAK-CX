#!/usr/bin/env bash
# ATAK-CX server installer.
#
# Sets up a private TAK server (OpenTAKServer) on a fresh Ubuntu, Debian or
# Raspberry Pi OS machine, locks it down, and installs the `takcx` command for
# adding buddies. Safe to re-run: finished steps are skipped.
#
#   git clone https://github.com/ryanpeh139/ATAK-CX.git
#   cd ATAK-CX
#   ./setup/install-server.sh
#
# Optional non-interactive settings:
#   TEAM_NAME="CX" SERVER_ADDRESS="mycrew.duckdns.org" ./setup/install-server.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
TEAM_CONF="$TAKCX_HOME/team.conf"
OTS_HEALTH_URL="http://127.0.0.1:8081/api/health"

bold=$'\e[1m'; green=$'\e[32m'; yellow=$'\e[33m'; red=$'\e[31m'; reset=$'\e[0m'
step() { echo; echo "${bold}${green}==> $*${reset}"; }
note() { echo "${yellow}$*${reset}"; }
die()  { echo "${red}Error: $*${reset}" >&2; exit 1; }
clean() {  # drop arrow-key escapes and other control characters from typed answers
  printf '%s' "$1" | sed $'s/\e\[[0-9;]*[A-Za-z]//g' | tr -cd '[:print:]' | sed 's/^ *//;s/ *$//'
}
ask() {  # ask "Question" default -> answer on stdout
  local answer
  read -r -e -p "$1 [${2}]: " answer < /dev/tty || true
  answer="$(clean "$answer")"
  echo "${answer:-$2}"
}
yes_no() {  # yes_no "Question" Y|N
  local answer
  read -r -e -p "$1 [$( [[ $2 == Y ]] && echo Y/n || echo y/N )]: " answer < /dev/tty || true
  answer="$(clean "$answer")"
  answer="${answer:-$2}"
  [[ $answer =~ ^[Yy] ]]
}
is_ip() { [[ $1 =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; }

# --------------------------------------------------------------------------- checks
step "Checking this machine"

[[ $EUID -ne 0 ]] || die "Don't run this as root. Create a normal user with sudo and log in as them:
    adduser tak && usermod -aG sudo tak && su - tak"

sudo -v || die "This user needs sudo rights."

[[ -r /etc/os-release ]] || die "Can't tell which Linux this is (no /etc/os-release)."
# shellcheck disable=SC1091
. /etc/os-release
if grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
  OTS_INSTALLER="raspberry_pi_installer"
elif [[ ${ID:-} == ubuntu ]]; then
  OTS_INSTALLER="ubuntu_installer"
elif [[ ${ID:-} == debian || ${ID:-} == raspbian ]]; then
  OTS_INSTALLER="debian_installer"
else
  die "Supported systems are Ubuntu, Debian and Raspberry Pi OS. This is ${PRETTY_NAME:-unknown}."
fi
echo "System: ${PRETTY_NAME:-$ID} ($(uname -m)), using OpenTAKServer's $OTS_INSTALLER"

mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
swap_mb=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)
echo "Memory: ${mem_mb} MB RAM, ${swap_mb} MB swap"
if (( mem_mb < 900 )); then
  die "This machine has only ${mem_mb} MB of RAM. OpenTAKServer uses about 1 GB just idling,
so it can't run here (that includes the Pi Zero 2 W and Pi 3A+). Swap on an SD card won't
save it: it would crawl and wear the card out. Use a cloud server or a Pi 4/5 with 2 GB+
instead. See docs/1-get-a-server.md."
fi
if (( mem_mb < 1800 )); then
  note "Under 2 GB of RAM. The server runs, but it's tight."
  if (( swap_mb < 1000 )) && yes_no "Add a 2 GB swap file so it doesn't run out of memory?" Y; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
    sudo swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    echo "Swap added."
  fi
fi

command -v curl >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq curl; }

# --------------------------------------------------------------------------- team settings
step "Team settings"
mkdir -p "$TAKCX_HOME"
chmod 700 "$TAKCX_HOME"

if [[ -f $TEAM_CONF ]]; then
  echo "Using existing $TEAM_CONF"
else
  public_ip="$(curl -fsS --max-time 5 https://api.ipify.org || true)"
  echo "Your buddies' phones need an address to reach this server. Best is a domain name"
  echo "(a free one from https://www.duckdns.org works) pointing at this server's public IP."
  echo "An IP address also works, but some features (clean share links) need a domain."
  [[ -n $public_ip ]] && echo "This server's public IP looks like: $public_ip"
  team_name="${TEAM_NAME:-$(ask "Team name (shown in ATAK)" "CX")}"
  server_address="${SERVER_ADDRESS:-$(ask "Server domain or IP" "${public_ip:-}")}"
  [[ -n $server_address ]] || die "A server address is required."
  # Make the values safe inside sed's replacement and inside double quotes.
  team_name="$(printf '%s' "$team_name" | tr -d '|"\\$`')"
  team_name="${team_name//&/\\&}"
  server_address="$(printf '%s' "$server_address" | tr -cd 'A-Za-z0-9.-')"
  sed -e "s|^TEAM_NAME=.*|TEAM_NAME=\"${team_name}\"|" \
      -e "s|^SERVER_ADDRESS=.*|SERVER_ADDRESS=\"${server_address}\"|" \
      "$REPO_DIR/team.conf.example" > "$TEAM_CONF"
  echo "Saved $TEAM_CONF (edit it any time)."
fi
# shellcheck disable=SC1090
. "$TEAM_CONF"

if ! is_ip "$SERVER_ADDRESS"; then
  resolved="$(getent ahostsv4 "$SERVER_ADDRESS" | awk 'NR==1 {print $1}' || true)"
  public_ip="${public_ip:-$(curl -fsS --max-time 5 https://api.ipify.org || true)}"
  if [[ -z $resolved ]]; then
    note "Heads up: $SERVER_ADDRESS doesn't resolve yet. Point its DNS at this server before adding buddies."
  elif [[ -n $public_ip && $resolved != "$public_ip" ]]; then
    note "Heads up: $SERVER_ADDRESS points to $resolved but this server's public IP is $public_ip."
  fi
fi

# --------------------------------------------------------------------------- OpenTAKServer
step "Installing OpenTAKServer"
if [[ -d $HOME/.opentakserver_venv ]] && systemctl is-enabled opentakserver >/dev/null 2>&1; then
  echo "Already installed, skipping. (Upgrade later with OpenTAKServer's own updater; see docs/maintenance.md.)"
else
  cat <<EOF
This runs the official OpenTAKServer installer. It takes 5-15 minutes and will ask
you two questions:

  ${bold}Install ZeroTier?${reset}      Answer ${bold}n${reset} on a cloud server.
                          Answer ${bold}y${reset} on a home server if you can't port-forward
                          (see docs/1-get-a-server.md first).
  ${bold}Install Mumble Server?${reset} Answer ${bold}n${reset}. If you want the team radio, this
                          script sets it up properly (locked to your accounts) afterwards.

EOF
  read -r -p "Press Enter to start..." < /dev/tty || true
  curl -fsSL "https://i.opentakserver.io/$OTS_INSTALLER" -o /tmp/ots_installer.sh
  bash /tmp/ots_installer.sh 2>&1 | tee "$HOME/ots_installer.log"
  rm -f /tmp/ots_installer.sh
fi

echo -n "Waiting for OpenTAKServer to come up"
for _ in $(seq 1 60); do
  curl -fsS --max-time 3 "$OTS_HEALTH_URL" >/dev/null 2>&1 && break
  echo -n "."; sleep 3
done
echo
curl -fsS --max-time 3 "$OTS_HEALTH_URL" >/dev/null 2>&1 \
  || die "OpenTAKServer isn't responding. Check ~/ots_installer.log and ~/ots/logs/opentakserver.log"
echo "OpenTAKServer is running."

# --------------------------------------------------------------------------- takcx
step "Installing the takcx command"
sudo apt-get install -y -qq qrencode >/dev/null
chmod +x "$REPO_DIR/takcx/takcx.py" "$REPO_DIR"/setup/*.sh
sudo ln -sf "$REPO_DIR/takcx/takcx.py" /usr/local/bin/takcx
echo "Installed: takcx -> $REPO_DIR/takcx/takcx.py"

if [[ ! -f $TAKCX_HOME/admin.conf ]]; then
  step "Replacing the default web admin password"
  takcx admin-password
fi

# --------------------------------------------------------------------------- firewall
step "Firewall"
cat <<EOF
Only these ports need to be open to the internet:
  80, 443     web map, share links, HTTPS certificate renewals
  8089        TAK clients (encrypted)
  8443        TAK data packages / API (needs a client certificate)
  8446        certificate enrollment
Everything else, including OpenTAKServer's unencrypted ports 8080 and 8088, gets blocked.
EOF
if yes_no "Turn on the firewall (ufw) with just those ports?" Y; then
  sudo apt-get install -y -qq ufw >/dev/null
  ssh_port="$(echo "${SSH_CONNECTION:-}" | awk '{print $4}')"
  ssh_port="${ssh_port:-22}"
  sudo ufw allow "$ssh_port/tcp" comment "SSH" >/dev/null
  for port in 80 443 8089 8443 8446; do
    sudo ufw allow "$port/tcp" comment "ATAK-CX" >/dev/null
  done
  if systemctl list-unit-files mumble-server.service 2>/dev/null | grep -q mumble-server; then
    sudo ufw allow 64738 comment "Mumble" >/dev/null
    echo "Opened 64738 for Mumble voice."
  fi
  if command -v zerotier-cli >/dev/null; then
    sudo ufw allow 9993/udp comment "ZeroTier" >/dev/null
    sudo ufw allow in on zt+ comment "ZeroTier network" >/dev/null
    echo "Allowed ZeroTier traffic."
  fi
  sudo ufw --force enable >/dev/null
  echo "Firewall on. SSH stays open on port $ssh_port."
else
  note "Skipped. Make sure ports 8080 and 8088 aren't reachable from the internet."
fi
note "If your cloud provider also has a firewall (AWS, Oracle, Google...), open the same ports there."

# --------------------------------------------------------------------------- radio
step "Team radio"
if [[ ${RADIO_ENABLED:-no} == yes ]]; then
  echo "Already set up. Re-run setup/enable-radio.sh after changing radio settings."
else
  echo "Push-to-talk voice channels (Mumble) using the same logins as the map."
  if yes_no "Set up the team radio?" Y; then
    "$REPO_DIR/setup/enable-radio.sh" || note "Radio setup failed; see above. You can re-run setup/enable-radio.sh"
    # shellcheck disable=SC1090
    . "$TEAM_CONF"
  fi
fi

# --------------------------------------------------------------------------- video
step "Live video (drones, cameras)"
if [[ ${VIDEO_ENABLED:-no} == yes ]]; then
  echo "Already on."
else
  echo "Stream DJI drones (DJI Fly app), IP cameras or phone cameras to everyone's ATAK and the web map."
  if yes_no "Turn on live video?" Y; then
    "$REPO_DIR/setup/enable-video.sh" || note "Video setup failed; see above. You can re-run setup/enable-video.sh"
    # shellcheck disable=SC1090
    . "$TEAM_CONF"
  fi
fi

# --------------------------------------------------------------------------- alerts
step "Emergency alerts to phones"
if [[ ${ALERTS_ENABLED:-no} == yes ]]; then
  echo "Already on."
else
  echo "When anyone hits the emergency button in ATAK, subscribed phones get a loud"
  echo "notification with a map link, even with ATAK closed (free ntfy app)."
  if yes_no "Turn on emergency alerts?" Y; then
    "$REPO_DIR/setup/enable-alerts.sh" || note "Alert setup failed; see above. You can re-run setup/enable-alerts.sh"
    # shellcheck disable=SC1090
    . "$TEAM_CONF"
  fi
fi

# --------------------------------------------------------------------------- public land maps
step "Public-land maps (US)"
if [[ ${PUBLICLAND_ENABLED:-no} == yes ]]; then
  echo "Already on."
else
  echo "Adds two maps to everyone's ATAK: topo and satellite with public land shaded"
  echo "(BLM, Forest Service, state, parks...) so you can see where private land starts."
  if yes_no "Turn on public-land maps?" Y; then
    "$REPO_DIR/setup/enable-publicland.sh" || note "Public-land setup failed; see above. You can re-run setup/enable-publicland.sh"
    # shellcheck disable=SC1090
    . "$TEAM_CONF"
  fi
fi

# --------------------------------------------------------------------------- aircraft
step "Aircraft on the map (ADS-B)"
if [[ ${AIRCRAFT_ENABLED:-no} == yes ]]; then
  echo "Already on (near ${AIRCRAFT_NEAR:-?}). Change area: takcx aircraft on --near \"Town, State\""
else
  echo "Show live planes and helicopters near you on everyone's map (free adsb.lol feed)."
  if yes_no "Turn on aircraft tracking?" Y; then
    near="$(ask "Center it on which town, or lat,lon" "")"
    if [[ -n $near ]]; then
      takcx aircraft on --near "$near" || note "Aircraft setup failed. Try later: takcx aircraft on --near \"Town, State\""
      # shellcheck disable=SC1090
      . "$TEAM_CONF"
    else
      note "Skipped. Turn it on later: takcx aircraft on --near \"Town, State\""
    fi
  fi
fi

# --------------------------------------------------------------------------- elevation
step "Elevation data for your area"
if [[ -n ${ELEVATION_URL:-} ]]; then
  echo "Already built (${ELEVATION_AREA:-?}). Rebuild or change area: takcx elevation --near \"Town\""
else
  echo "Detailed 30 m terrain data so ATAK's elevation, slope and line-of-sight tools work"
  echo "properly, even offline. Everyone gets a download link on their welcome page."
  if yes_no "Build elevation data for your area?" Y; then
    elev_near="${AIRCRAFT_NEAR:-}"
    elev_near="$(ask "Center it on which town, or lat,lon" "$elev_near")"
    if [[ -n $elev_near ]]; then
      command -v gdalwarp >/dev/null || sudo apt-get install -y -qq gdal-bin >/dev/null
      takcx elevation --near "$elev_near" --radius 50 \
        || note "Elevation build failed. Try later: takcx elevation --near \"Town\""
      # shellcheck disable=SC1090
      . "$TEAM_CONF"
    else
      note "Skipped. Build it later: takcx elevation --near \"Town, State\""
    fi
  fi
fi

# --------------------------------------------------------------------------- HTTPS
if ! is_ip "$SERVER_ADDRESS" && [[ ${HTTPS_ENABLED:-no} != yes ]]; then
  step "HTTPS (Let's Encrypt)"
  echo "With a real certificate, share links open without a browser warning."
  if yes_no "Get a free certificate for $SERVER_ADDRESS now?" Y; then
    "$REPO_DIR/setup/enable-https.sh" || note "HTTPS setup failed. Fix DNS/ports and re-run setup/enable-https.sh"
  fi
fi

# --------------------------------------------------------------------------- backups
step "Nightly backups"
if crontab -l 2>/dev/null | grep -q "setup/backup.sh"; then
  echo "Already scheduled."
elif yes_no "Back up the server's certificates and database every night (kept 14 days)?" Y; then
  (crontab -l 2>/dev/null; echo "17 3 * * * $REPO_DIR/setup/backup.sh >> $TAKCX_HOME/backup.log 2>&1") | crontab -
  echo "Scheduled for 03:17 daily into ~/takcx-backups. Copy them off the server now and then."
fi

# --------------------------------------------------------------------------- done
# shellcheck disable=SC1090
. "$TEAM_CONF"
step "All set!"
cat <<EOF
Web map & admin:  https://$SERVER_ADDRESS/
Admin login:      see $TAKCX_HOME/admin.conf
Team radio:       $( [[ ${RADIO_ENABLED:-no} == yes ]] && echo "$SERVER_ADDRESS port 64738 (Mumla / Mumble apps)" || echo "off (turn on: setup/enable-radio.sh)" )
Live video:       $( [[ ${VIDEO_ENABLED:-no} == yes ]] && echo "on (drones: takcx add-drone drone1 --share)" || echo "off (turn on: setup/enable-video.sh)" )
Emergency alerts: $( [[ ${ALERTS_ENABLED:-no} == yes ]] && echo "on (ntfy topic: ${NTFY_TOPIC:-?})" || echo "off (turn on: setup/enable-alerts.sh)" )
Public-land maps: $( [[ ${PUBLICLAND_ENABLED:-no} == yes ]] && echo "on" || echo "off (turn on: setup/enable-publicland.sh)" )
Elevation data:   $( [[ -n ${ELEVATION_URL:-} ]] && echo "${ELEVATION_AREA:-built} (${ELEVATION_SIZE:-})" || echo "none (build: takcx elevation --near \"Town\")" )
Aircraft:         $( [[ ${AIRCRAFT_ENABLED:-no} == yes ]] && echo "on, near ${AIRCRAFT_NEAR:-?}" || echo "off (turn on: takcx aircraft on --near \"Town\")" )

Add your first buddy (and yourself!):
  ${bold}takcx add yourname --role "Team Lead" --share${reset}
  ${bold}takcx add bob --share${reset}

Then send each person their link. More: takcx --help, and docs/2-add-buddies.md
Check health any time with: ${bold}takcx doctor${reset}
EOF

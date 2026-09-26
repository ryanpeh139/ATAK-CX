#!/usr/bin/env bash
# Live video: drones (DJI Fly RTMP), IP cameras and phone cameras streamed to
# the team, watchable in ATAK and on the web map. OpenTAKServer already runs the
# video server (MediaMTX); this opens it up and records the setting.
#
#   ./setup/enable-video.sh        (install-server.sh offers to run this)
#
# Then give each drone its own login: takcx add-drone drone1 --share
set -euo pipefail

TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
TEAM_CONF="$TAKCX_HOME/team.conf"
MTX_CONF="${OTS_DATA_FOLDER:-$HOME/ots}/mediamtx/mediamtx.yml"

die() { echo "Error: $*" >&2; exit 1; }

[[ $EUID -ne 0 ]] || die "Run this as the same (non-root) user you ran install-server.sh as."
[[ -f $TEAM_CONF ]] || die "No $TEAM_CONF. Run setup/install-server.sh first."
[[ -f $MTX_CONF ]] || die "OpenTAKServer's video server config ($MTX_CONF) isn't there."
# shellcheck disable=SC1090
. "$TEAM_CONF"

# Browsers outside your network need the server's public address for WebRTC.
if [[ -n ${SERVER_ADDRESS:-} ]] && grep -q '^webrtcAdditionalHosts: \[\]' "$MTX_CONF"; then
  sed -i "s/^webrtcAdditionalHosts: \[\]/webrtcAdditionalHosts: [\"$SERVER_ADDRESS\"]/" "$MTX_CONF"
  echo "Web video will advertise $SERVER_ADDRESS to browsers."
fi

sudo systemctl enable mediamtx >/dev/null 2>&1 || true
sudo systemctl restart mediamtx
sleep 2
systemctl is-active --quiet mediamtx || die "The video server (mediamtx) won't start: journalctl -u mediamtx -n 50"

if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow 1935/tcp comment "ATAK-CX video in (RTMP, drones)" >/dev/null
  sudo ufw allow 8554/tcp comment "ATAK-CX video to ATAK (RTSP)" >/dev/null
  sudo ufw allow 8189/udp comment "ATAK-CX web video (WebRTC)" >/dev/null
  echo "Firewall: opened 1935/tcp, 8554/tcp, 8189/udp."
fi

sed -i 's/^VIDEO_ENABLED=.*/VIDEO_ENABLED="yes"/' "$TEAM_CONF"
grep -q '^VIDEO_ENABLED=' "$TEAM_CONF" || echo 'VIDEO_ENABLED="yes"' >> "$TEAM_CONF"

if [[ -n $(ls -A "$TAKCX_HOME/buddies" 2>/dev/null) ]]; then
  "$(dirname "${BASH_SOURCE[0]}")/../takcx/takcx.py" rebuild --all >/dev/null \
    && echo "Added live-video instructions to everyone's welcome page."
fi

cat <<EOF

Live video is on.
  Drones:   takcx add-drone drone1 --share   (gives you a page to open on the DJI Fly phone)
  Watching: ATAK -> Video Player -> download button, or the web map -> Video Streams
Home server? Also forward 1935/tcp, 8554/tcp and 8189/udp on your router.
EOF

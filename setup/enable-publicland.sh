#!/usr/bin/env bash
# Public-land maps (US): land ownership (BLM, Forest Service, state, parks...)
# blended over USGS topo and USGS satellite imagery, served by your server and
# added to everyone's ATAK package as two extra maps.
#
#   ./setup/enable-publicland.sh        (install-server.sh offers to run this)
#
# Re-run it after upgrading OpenTAKServer (its updater can replace nginx configs).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
TEAM_CONF="$TAKCX_HOME/team.conf"
OTS_PY="$HOME/.opentakserver_venv/bin/python"
SITE=/etc/nginx/sites-available/ots_https

die() { echo "Error: $*" >&2; exit 1; }

[[ $EUID -ne 0 ]] || die "Run this as the same (non-root) user you ran install-server.sh as."
[[ -f $TEAM_CONF ]] || die "No $TEAM_CONF. Run setup/install-server.sh first."
[[ -x $OTS_PY ]] || die "OpenTAKServer isn't installed for this user."
[[ -f $SITE ]] || die "OpenTAKServer's nginx site ($SITE) isn't there."
"$OTS_PY" -c "import PIL" 2>/dev/null || die "OpenTAKServer's Python is missing Pillow."
# shellcheck disable=SC1090
. "$TEAM_CONF"

sudo tee /etc/systemd/system/takcx-tiles.service >/dev/null <<EOF
[Unit]
Description=ATAK-CX public-land map tiles
After=network-online.target

[Service]
User=$(whoami)
Environment=TAKCX_TILE_CACHE=$TAKCX_HOME/tile-cache
ExecStart=$OTS_PY $REPO_DIR/takcx/tile_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable takcx-tiles >/dev/null 2>&1
sudo systemctl restart takcx-tiles

sudo python3 "$REPO_DIR/setup/nginx_add_location.py" "$SITE" /tiles/ 8095
sudo nginx -t
sudo systemctl reload nginx

echo -n "Testing a tile"
ok=no
for _ in $(seq 1 10); do
  sleep 2; echo -n "."
  if curl -fsk -o /dev/null --max-time 30 "https://127.0.0.1/tiles/publicland-topo/4/3/6.jpg"; then ok=yes; break; fi
done
echo
[[ $ok == yes ]] || die "Tiles aren't coming through. Check: journalctl -u takcx-tiles -n 30"

sed -i 's/^PUBLICLAND_ENABLED=.*/PUBLICLAND_ENABLED="yes"/' "$TEAM_CONF"
grep -q '^PUBLICLAND_ENABLED=' "$TEAM_CONF" || echo 'PUBLICLAND_ENABLED="yes"' >> "$TEAM_CONF"

if [[ -n $(ls -A "$TAKCX_HOME/buddies" 2>/dev/null) ]]; then
  "$REPO_DIR/takcx/takcx.py" rebuild --all >/dev/null && echo "Added the public-land maps to everyone's package."
fi

cat <<EOF

Public-land maps are on: "Public Land + Topo (US)" and "Public Land + Satellite (US)".
People who already joined: re-import their package (or send them: takcx maps).
EOF
if [[ ${HTTPS_ENABLED:-no} != yes ]]; then
  echo "Note: set up HTTPS (setup/enable-https.sh) so ATAK trusts the map server."
fi

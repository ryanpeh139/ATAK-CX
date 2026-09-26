#!/usr/bin/env bash
# Update everything: ATAK-CX, OpenTAKServer (server + web map) and everyone's welcome
# pages, then run the health check. Backs up first; keeps everyone's links and files.
#
#   ./setup/update.sh              (the Manager's Settings -> Update everything runs this too)
#   ./setup/update.sh --check      just say what's out of date
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
OTS_PY="${OTS_PYTHON:-$HOME/.opentakserver_venv/bin/python}"
TAKCX=("$OTS_PY" "$REPO_DIR/takcx/takcx.py")
LOG="$TAKCX_HOME/last-update.log"
SUDO=(sudo); [[ -t 0 ]] || SUDO=(sudo -n)   # the Manager has no terminal to type a password in

[[ $EUID -ne 0 ]] || { echo "Error: run this as your normal user, not root." >&2; exit 1; }

if [[ ${1:-} == --check ]]; then
  git -C "$REPO_DIR" fetch -q origin 2>/dev/null || true
  behind=$(git -C "$REPO_DIR" rev-list --count 'HEAD..@{u}' 2>/dev/null || echo "?")
  echo "ATAK-CX:       $(git -C "$REPO_DIR" log -1 --format='%h (%cs)') - $behind update(s) waiting"
  exec "$OTS_PY" "$REPO_DIR/takcx/ots_update.py" --check
fi

# Step 1 gets the newest ATAK-CX, then re-runs the new copy of this script for the rest.
if [[ ${1:-} != --after-pull ]]; then
  mkdir -p "$TAKCX_HOME"
  {
    echo "Update started $(date '+%Y-%m-%d %H:%M')"
    echo "== 1/4 ATAK-CX"
    before=$(git -C "$REPO_DIR" rev-parse HEAD)
    git -C "$REPO_DIR" pull --ff-only
    if [[ $(git -C "$REPO_DIR" rev-parse HEAD) != "$before" ]]; then
      git -C "$REPO_DIR" log --format='  %cs  %s' "$before..HEAD" | head -20
    fi
  } 2>&1 | tee "$LOG"
  exec "$REPO_DIR/setup/update.sh" --after-pull
fi

{
  echo "== 2/4 OpenTAKServer and the web map"
  "$OTS_PY" "$REPO_DIR/takcx/ots_update.py"

  # The web map gets the Manager's look and login (unless it was turned off).
  if grep -q '^MANAGER_ENABLED="yes"' "$TAKCX_HOME/team.conf" && ! grep -q '^WEBMAP_THEME="no"' "$TAKCX_HOME/team.conf"; then
    "${TAKCX[@]}" webmap-theme on || echo "(Couldn't theme the web map; see above.)"
  fi

  echo "== 3/4 Welcome pages and packages"
  if [[ -n $(ls -A "$TAKCX_HOME/buddies" 2>/dev/null) ]]; then
    "${TAKCX[@]}" rebuild --all
  else
    echo "Nobody added yet."
  fi

  echo "== 4/4 Health check"
  "${TAKCX[@]}" doctor || echo "(The health check found something; see above.)"
  echo "Update finished $(date '+%Y-%m-%d %H:%M')"
} 2>&1 | tee -a "$LOG"   # a failed step stops here (set -e), so its output stays on screen

# Last, so the Manager (which may be running this) comes back on the new version.
if systemctl is-active --quiet takcx-manager 2>/dev/null; then
  echo "Restarting the Manager..."
  "${SUDO[@]}" systemctl restart takcx-manager || echo "Couldn't restart it: sudo systemctl restart takcx-manager"
fi

#!/usr/bin/env bash
# Keep a free DuckDNS name (e.g. mycrew.duckdns.org) pointed at this server's
# public IP, which matters for a home server whose IP can change.
#
#   ./setup/duckdns.sh mycrew YOUR-DUCKDNS-TOKEN
#
# Get the name and token at https://www.duckdns.org (sign in, add a domain;
# the token is shown at the top of the page). Updates every 5 minutes.
set -euo pipefail

name="${1:-}"; token="${2:-}"
name="${name%.duckdns.org}"
if [[ -z $name || -z $token ]]; then
  echo "Usage: $0 NAME TOKEN     (NAME is the part before .duckdns.org)" >&2
  exit 1
fi
[[ $name =~ ^[a-z0-9-]+$ ]] || { echo "Error: '$name' isn't a valid DuckDNS name." >&2; exit 1; }
[[ $token =~ ^[a-f0-9-]+$ ]] || { echo "Error: that doesn't look like a DuckDNS token." >&2; exit 1; }

dir="$HOME/duckdns"
mkdir -p "$dir"
chmod 700 "$dir"
cat > "$dir/update.sh" <<EOF
#!/bin/sh
# Written by ATAK-CX setup/duckdns.sh. Leaving ip= empty lets DuckDNS use the address it sees.
curl -fsS --max-time 30 "https://www.duckdns.org/update?domains=$name&token=$token&ip=" -o "$dir/last.log"
EOF
chmod 700 "$dir/update.sh"

"$dir/update.sh"
if [[ $(cat "$dir/last.log") != OK ]]; then
  echo "Error: DuckDNS said '$(cat "$dir/last.log")'. Check the name and token." >&2
  exit 1
fi

(crontab -l 2>/dev/null | grep -v "$dir/update.sh"; echo "*/5 * * * * $dir/update.sh >/dev/null 2>&1") | crontab -
echo "$name.duckdns.org now points here, and is refreshed every 5 minutes."
echo "Use $name.duckdns.org as the server address in install-server.sh."

#!/usr/bin/env bash
# Get a free Let's Encrypt certificate for the web map, share links and
# certificate enrollment (ports 443 and 8446), following OpenTAKServer's docs.
# TAK traffic on 8089/8443 keeps using the server's own certificate authority,
# so packages you already handed out keep working.
#
#   ./setup/enable-https.sh                       # uses SERVER_ADDRESS from team.conf
#   ./setup/enable-https.sh mycrew.duckdns.org you@example.com
#
# Needs: a domain whose DNS points at this server, and port 80 reachable.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
TEAM_CONF="$TAKCX_HOME/team.conf"
NGINX_SITES=/etc/nginx/sites-available

die() { echo "Error: $*" >&2; exit 1; }

# shellcheck disable=SC1090
[[ -f $TEAM_CONF ]] && . "$TEAM_CONF"
domain="${1:-${SERVER_ADDRESS:-}}"
email="${2:-}"
[[ -n $domain ]] || die "Usage: $0 your.domain.com [email]"
[[ ! $domain =~ ^[0-9.]+$ ]] || die "Let's Encrypt needs a domain name, not an IP ($domain). See docs/1-get-a-server.md for a free DuckDNS name."
[[ -f $NGINX_SITES/ots_https ]] || die "OpenTAKServer's nginx config isn't there. Run setup/install-server.sh first."

if [[ -z $email ]]; then
  read -r -p "Email for expiry warnings from Let's Encrypt (optional, Enter to skip): " email < /dev/tty || true
fi

echo "Requesting a certificate for $domain..."
sudo apt-get install -y -qq certbot >/dev/null
if [[ -n $email ]]; then account=(-m "$email"); else account=(--register-unsafely-without-email); fi

# certbot's standalone mode needs port 80, which nginx holds. Always bring nginx back.
sudo systemctl stop nginx
trap 'sudo systemctl start nginx' EXIT
sudo certbot certonly --standalone --preferred-challenges http --non-interactive --agree-tos \
  "${account[@]}" -d "$domain"

# Same dance on every automatic renewal.
sudo mkdir -p /etc/letsencrypt/renewal-hooks/pre /etc/letsencrypt/renewal-hooks/post
echo -e '#!/bin/sh\nsystemctl stop nginx' | sudo tee /etc/letsencrypt/renewal-hooks/pre/takcx-stop-nginx.sh >/dev/null
echo -e '#!/bin/sh\nsystemctl start nginx' | sudo tee /etc/letsencrypt/renewal-hooks/post/takcx-start-nginx.sh >/dev/null
sudo chmod +x /etc/letsencrypt/renewal-hooks/pre/takcx-stop-nginx.sh \
  /etc/letsencrypt/renewal-hooks/post/takcx-start-nginx.sh

echo "Pointing nginx at the new certificate (backups saved as *.takcx-bak)..."
sudo python3 "$REPO_DIR/setup/nginx_use_cert.py" "$domain" \
  "$NGINX_SITES/ots_https" "$NGINX_SITES/ots_certificate_enrollment"

sudo nginx -t
trap - EXIT
sudo systemctl start nginx

if [[ -f $TEAM_CONF ]]; then
  sed -i 's/^HTTPS_ENABLED=.*/HTTPS_ENABLED="yes"/' "$TEAM_CONF"
  grep -q '^HTTPS_ENABLED=' "$TEAM_CONF" || echo 'HTTPS_ENABLED="yes"' >> "$TEAM_CONF"
fi

echo
echo "HTTPS is on: https://$domain/"
echo "Certificates renew automatically (check with: sudo certbot renew --dry-run)."

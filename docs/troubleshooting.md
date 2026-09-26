# Troubleshooting

Start with this on the server. It checks services, DNS, ports and the firewall:

```bash
takcx doctor
```

## A phone won't connect (server icon stays red)

Work down the list:

1. **Phone date and time** must be set automatically. Certificates fail with a
   wrong clock.
2. **Can the phone reach the server at all?** Open `https://your-server/` in the
   phone's browser. If it doesn't load, the problem is network, not TAK:
   - Cloud server: open ports 443, 8089, 8443, 8446 in the provider's firewall.
   - Home server: check port forwarding, and check for CGNAT
     (see [server guide](1-get-a-server.md#option-b-home-server-raspberry-pi-45-or-old-pc)).
   - ZeroTier: is ZeroTier switched on on the phone, and is the phone approved
     in the ZeroTier dashboard?
3. **Is the account enabled?** `takcx list`, then `takcx enable NAME`.
4. **Old package?** If you changed the server address or rebuilt packages, they
   need the new one. Delete the old server in ATAK (Settings → Network
   Preferences → TAK Servers), then import the new package.
5. **Watch the server log while they try:**
   ```bash
   tail -f ~/ots/logs/opentakserver.log ~/ots/logs/eud_handler_ssl.log
   ```
   A line like `bob is ID'ed by cert` means they got in. `does not exist` or
   `deactivated` means the account is the problem.

## "TAK Server's identity could not be verified" or a certificate error

ATAK only trusts the certificate inside the package, and Let's Encrypt/DigiCert
for enrollment. Usually this means the package came from a different or
reinstalled server (reinstalling creates a new certificate authority). Rebuild and
resend: `takcx rebuild NAME`, then `takcx share NAME`.

## Share link shows the OpenTAKServer login page instead of the join page

The link must end in `/index.html`. Copy it exactly from `takcx share NAME`.
If an OpenTAKServer upgrade wiped the web folder, run `takcx share NAME` again
to republish (the link stays the same).

## Browser warns "not secure" on the share link

HTTPS isn't set up (or you're using an IP address). With a domain, run
`./setup/enable-https.sh`. Until then people can tap **Advanced → Proceed**.

## HTTPS setup (Let's Encrypt) fails

- The domain must point at this server: `getent hosts your.domain` should show
  the same IP as `curl https://api.ipify.org`.
- Port 80 must be reachable from the internet (cloud firewall / router).
- DuckDNS changes can take a few minutes to spread.

## Something's down

```bash
sudo systemctl status opentakserver eud_handler_ssl nginx rabbitmq-server postgresql
sudo systemctl restart opentakserver eud_handler eud_handler_ssl cot_parser
```

Logs are in `~/ots/logs/`. The installer log is `~/ots_installer.log`.

## `takcx doctor` says cot_parser is inactive

Its log (`~/ots/logs/cot_parser.log`) says `no exchange 'cot_parser'`: it started
before OpenTAKServer was ready and gave up. Current installers add an automatic
retry. To fix it by hand:

```bash
sudo mkdir -p /etc/systemd/system/cot_parser.service.d
printf '[Unit]\nAfter=opentakserver.service\nStartLimitIntervalSec=0\n\n[Service]\nRestart=always\nRestartSec=10\n' | sudo tee /etc/systemd/system/cot_parser.service.d/takcx-retry.conf
sudo systemctl daemon-reload && sudo systemctl restart cot_parser
```

## takcx says "Admin login failed"

Someone changed the admin password in the web UI. Put the new one in
`~/takcx/admin.conf` (`OTS_ADMIN_PASSWORD="..."`).

## Aircraft don't show up

- `takcx doctor` should say "aircraft updates running". If not: `takcx aircraft on`.
- Buddies need to be in the aircraft group: `takcx aircraft sync`, then they
  toggle the server connection off/on in ATAK once.
- Nothing flying nearby? Try a bigger area: `takcx aircraft on --radius 150`.

## Drone or camera video doesn't work

- `takcx doctor` should show `mediamtx` active and ports 1935 and 8554 listening.
- Home server: 1935/tcp, 8554/tcp and 8189/udp must be forwarded on the router.
- DJI Fly says it can't connect: re-copy the address from the drone's page
  (`takcx share drone1`); the phone/controller needs internet while streaming.
- ATAK shows the stream but it won't play: edit the stream in Video Player and
  enter your takcx username and password.

## Still stuck

OpenTAKServer has good [docs](https://docs.opentakserver.io) and an active
[Discord](https://discord.gg/6uaVHjtfXN).

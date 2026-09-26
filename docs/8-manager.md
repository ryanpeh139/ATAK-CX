# 8. ATAK-CX Manager (web dashboard)

A web page for running your server without SSH:
**`https://<your-server>/manage/`**

| Page | What you can do |
|---|---|
| **Status** | Every service and add-on at a glance, disk space, last backup, a full health check |
| **People** | Add people (with their private link and QR code on screen), make or take down links, disable/enable, rebuild, remove |
| **Drones** | Add a drone login and get its DJI Fly setup page |
| **Add-ons** | Change the aircraft area, build elevation data, send a test emergency alert, see what's on |
| **Plugins** | Upload an ATAK plugin (pushed to everyone), see and remove plugins |
| **Settings** | Team name, default color/role, coordinate format, radio channels, Discord/Telegram for alerts |
| **Backups** | Back up now, download backups |
| **Troubleshoot** | Recent radio logins and TAK connections, each with the reason it was refused; restart buttons for every service; recent errors |
| **Jobs** | Every action runs as a job; watch its output live |

Click anyone's name (or **Show login**) to see their username, password and welcome-page
link with its QR code, or give them a **new password**. Their ATAK stays connected
because it uses a certificate; only the radio, web map and video use the password.

**Anyone on the team can change their own password** at `https://<your-server>/manage/password`
(no admin needed; the link is on everyone's welcome page and the Manager's login page). They
enter their current password (and their two-factor code if they turned it on). Once
they've picked their own, the Manager shows "picked their own" instead of the password. If they
forget it, use **Make a new password**.

**Settings → Updates** shows what's installed and what's newer, for ATAK-CX,
OpenTAKServer and the web map. **Update everything** backs up first, updates all three
(keeping everyone's links and files), refreshes everyone's welcome pages, runs the health
check and restarts the Manager. The log of the last update stays on that page. Details:
[maintenance](maintenance.md#updating-atak-cx-opentakserver-and-the-web-map). If an update
adds a new add-on or changes permissions, its notes will say which setup script to re-run
over SSH.

## Turn it on

The installer asks. To do it later:

```bash
cd ~/ATAK-CX
./setup/enable-manager.sh
```

## Log in with your own admin account (and turn on two-factor)

The built-in `administrator` account is what `takcx` uses behind the scenes.
Its password lives in `~/takcx/admin.conf`, and it **must not** get two-factor login,
or `takcx` stops working. So make yourself your own admin account:

```bash
takcx add ryan --admin --share
```

That's also your normal ATAK login, with a callsign and a welcome page like
everyone else's. Then **turn on two-factor** for it:

1. Open the web map (`https://<your-server>/`) and log in as **ryan** with the password
   from your welcome page (or `~/takcx/buddies/ryan/credentials.txt`).
2. Click **Setup 2FA** in the menu → choose the **authenticator app** option.
3. Scan the QR code with Google Authenticator, Microsoft Authenticator or similar,
   and enter the code it shows.

From then on the Manager (and the web map) asks for the 6-digit code after your
password. ATAK, the radio and video aren't affected.

## What it can and can't do

- It runs the same `takcx` commands you'd type, so anything done here matches the
  command line and the rest of the docs.
- It can **restart** a fixed list of ATAK-CX and OpenTAKServer services (and itself,
  for updates) and read two logs. That list is in
  `/etc/sudoers.d/takcx-manager`. It **can't** install software or change system
  settings, so turning on radio, video, alerts, public-land maps or HTTPS still
  happens over SSH. The Add-ons page shows the exact command for each.
- Changing the **server address** is SSH-only too, because everyone needs new files
  afterwards.

## Security notes

- Only OpenTAKServer **administrator** accounts can log in. Buddies can't.
- 5 wrong passwords or codes from one address → locked out for 5 minutes (the
  change-password page counts too).
- The change-password page only changes accounts made with takcx, never the built-in
  `administrator` account or drone logins.
- Sessions last 12 hours; the cookie is HTTPS-only and can't be read by scripts
  or used by other sites. Every form carries an anti-forgery token.
- The page loads no outside scripts or fonts, and can't be embedded in another site.
- Backups contain everyone's keys. Download them only on a device you trust.

## Troubleshooting

```bash
sudo systemctl status takcx-manager
journalctl -u takcx-manager -n 50
```

If `https://<server>/manage/` shows the OpenTAKServer page instead, re-run
`./setup/enable-manager.sh`. An OpenTAKServer upgrade can replace its nginx config,
and this puts the `/manage/` entry back. The same applies to
`./setup/enable-publicland.sh` for the public-land maps.

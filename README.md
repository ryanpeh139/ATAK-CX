# ATAK-CX

A private TAK setup for you and your buddies: your own server, your own team
map, and **one file per person** to get them connected. No fiddling with
certificates, ports or server settings on anyone's phone.

- **Works with:** ATAK (Android), iTAK (iPhone/iPad), WinTAK (Windows)
- **You get:** live positions, encrypted team chat, a push-to-talk **team radio**
  (voice channels locked to your team), shared markers, routes and photos,
  emergency alerts, a web map in your browser, and satellite + topo maps
  (downloadable for offline use) already loaded on every device.
- **Built on:** [OpenTAKServer](https://github.com/brian7704/OpenTAKServer),
  a free, open-source TAK server. The apps are the standard free TAK apps;
  what ATAK-CX customizes is the setup: your team name, callsigns, team colors,
  roles and maps are all set for each person automatically.

## How it works

```
 you (once)                          each buddy (2 minutes)
 ──────────                          ──────────────────────
 1. rent a small server / use a Pi   1. install ATAK / iTAK / WinTAK
 2. ./setup/install-server.sh        2. open the link you sent them
 3. takcx add bob --share            3. tap download, import into the app
    → sends you a private link          → connected, callsign + maps set
```

## Quick start

**1. Get a server.** A $5–12/month cloud server (Ubuntu 24.04, 2 GB+ RAM) is the
easiest. A Raspberry Pi 4/5 (2 GB+) or old PC at home also works.
[Help picking one →](docs/1-get-a-server.md)

**2. Install.** SSH into the server as a normal user with sudo (not root) and run:

```bash
git clone https://github.com/ryanpeh139/ATAK-CX.git
cd ATAK-CX
./setup/install-server.sh
```

It asks for a team name and the server's address, installs OpenTAKServer,
sets a strong admin password, turns on a firewall, sets up the team radio,
gets an HTTPS certificate (if you use a domain name) and schedules nightly
backups. It takes about 15–30 minutes (longer on a Raspberry Pi).

> If this repo is private, clone it on the server with a
> [GitHub token](https://github.com/settings/tokens) or make it public.
> It contains no secrets: passwords and keys are generated on the server.

**3. Add people** (start with yourself):

```bash
takcx add ryan --role "Team Lead" --share
takcx add bob --callsign Bobcat --color Red --role Medic --share
```

Each `--share` prints a private link (and a QR code). Text it to that person.
It opens a page with the right download and steps for their device.
[More on adding buddies →](docs/2-add-buddies.md)

## Everyday commands

| Command | What it does |
|---|---|
| `takcx add NAME [--callsign X] [--color C] [--role R] [--share]` | Add someone |
| `takcx list` | Everyone, and whether they're enabled |
| `takcx share NAME` / `takcx unshare NAME` | Publish or take down their download link |
| `takcx disable NAME` / `takcx enable NAME` | Lock someone out (lost phone?) or let them back in |
| `takcx remove NAME` | Delete someone for good |
| `takcx rebuild --all` | Remake everyone's packages after editing `~/takcx/team.conf` or `maps/` |
| `takcx maps` | A maps-only package: no login in it, safe to share with anyone |
| `takcx doctor` | Check that everything is running and reachable |

The web map and admin panel are at `https://your-server/` (login in `~/takcx/admin.conf`).

## Guides

1. [Get a server](docs/1-get-a-server.md): cloud vs. home, free domain names, ports
2. [Add buddies](docs/2-add-buddies.md): colors, roles, sharing, lost phones
3. [Maps, offline use and radios](docs/3-maps-offline-radio.md): offline maps, no-server mode, Meshtastic, ham radio rules
4. [Team radio](docs/4-radio.md): push-to-talk voice channels
5. [Plugins and extras](docs/5-plugins.md): push plugins to everyone, aircraft on the map, live video
6. [Meshtastic gear](docs/6-meshtastic-gear.md): which off-grid radios to buy and how to set them up
7. [Troubleshooting](docs/troubleshooting.md)
8. [Backups, restore and upgrades](docs/maintenance.md)

## What's in this repo

```
setup/install-server.sh   one-command server install
setup/enable-https.sh     free Let's Encrypt certificate (run by the installer)
setup/enable-radio.sh     team radio: Mumble locked to takcx accounts (run by the installer)
setup/backup.sh           nightly backup of certificates, database and packages
takcx/takcx.py            the `takcx` command
maps/*.xml                map sources bundled into every package (add your own)
team.conf.example         team settings template (lives at ~/takcx/team.conf)
```

## Security in one paragraph

Every device gets its own certificate, and all TAK traffic is encrypted. The
firewall only opens the ports TAK needs, and OpenTAKServer's unencrypted ports
stay closed. A connection package *is* someone's login: send it privately,
take share links down once people have joined (`takcx unshare`), and
`takcx disable` anyone whose phone goes missing. Backups contain your
certificate authority, so keep them somewhere private.

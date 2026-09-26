# Install guide: from a blank Raspberry Pi to your team on the map

This walks through everything, in order, for a **Raspberry Pi 4 or 5 at home**.
Notes for a cloud server are marked ☁️. Set aside about an hour. Most of it is
waiting for the installer.

**Tick these off as you go:**

- [ ] 1. Flash the SD card
- [ ] 2. Connect to the Pi
- [ ] 3. Give the Pi a fixed address on your network
- [ ] 4. Set up outside access (free domain + port forwarding)
- [ ] 5. Download ATAK-CX onto the Pi
- [ ] 6. Run the installer
- [ ] 7. Check it works from outside
- [ ] 8. Add yourself and your buddies
- [ ] 9. Extras: radio, drones, aircraft, plugins, Meshtastic

---

## What you need

| | |
|---|---|
| **Raspberry Pi 4 or 5, 2 GB+ RAM** | 4 GB+ is comfortable. A Pi Zero or Pi 3 won't work. |
| **Official power supply** | Pi 4: 5V/3A USB-C. Pi 5: 5V/5A. Not a computer's USB port. |
| **microSD card, 32 GB+, "A2" rated** | Or better, a USB SSD. The database writes constantly and wears out cheap cards. |
| **Ethernet cable to your router** | Recommended. Wi-Fi works, but a server should be wired. |
| **A computer** | Windows, Mac or Linux, to flash the card and type commands. |
| **Your router's admin login** | Usually on a sticker on the router. Needed for step 4. |

☁️ **Cloud server instead?** Create an Ubuntu 24.04 server with 2 GB+ RAM, make
a normal user (`adduser tak && usermod -aG sudo tak`), and skip to step 4B
(free domain). There's no port forwarding to do; open the ports in your provider's
firewall instead (list in step 4C).

---

## 1. Flash the SD card

1. Install **[Raspberry Pi Imager](https://www.raspberrypi.com/software/)** on
   your computer and put the SD card in.
2. **Choose Device:** your Pi (e.g. Raspberry Pi 4).
   **Choose OS:** *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)**.
   **Choose Storage:** your SD card.
3. Click **Next** → **Edit Settings** (newer Imager versions call this the *Customisation* step):
   - **Hostname:** `takserver`
   - **Username and password:** pick them and write them down. This is your
     login for the Pi (e.g. username `ryan`).
   - **Wireless LAN:** your Wi-Fi name and password. Skip this if you're using Ethernet.
   - **Locale:** your time zone.
   - **Services** tab: tick **Enable SSH** → *Use password authentication*.
4. **Save** → **Yes** → wait for it to write and verify.
5. Put the card in the Pi, plug in Ethernet, then power. Wait **3–5 minutes**
   (the first boot restarts once).

**Lights:** red solid + green flickering = booting ✅. Only red = bad card or
image, so flash again. Red blinking = not enough power.

---

## 2. Connect to the Pi

On your computer, open a terminal: **Windows:** Start → type *Terminal* (or
*PowerShell*). **Mac:** *Terminal*.

```
ssh yourusername@takserver.local
```

Type `yes` if it asks about a fingerprint, then your Pi password (nothing shows
as you type; that's normal).

**"Could not resolve hostname"?** Find the Pi's IP instead: log into your router
and look for `takserver` in the device list, or use the free **Fing** phone app.
Then: `ssh yourusername@192.168.x.x`.

You're in when the prompt looks like `yourusername@takserver:~ $`.

---

## 3. Give the Pi a fixed address on your network

Port forwarding (next step) points at the Pi's local IP, so that IP must never
change. In your router's admin page find **DHCP reservation** (also called
*Address reservation*, *Static lease* or *Fixed IP*) and reserve the Pi's
current IP. To see the Pi's IP, run:

```
hostname -I
```

---

## 4. Set up outside access

Your buddies' phones need to reach the Pi from anywhere. The steps depend on
your internet connection.

### 4A. Check: can you port-forward at all?

**Phone hotspot?** If the Pi is on a phone's hotspot (addresses like
`192.168.43.x` or `172.20.10.x` are common), it can't be reached from outside.
Put it on your home router, or use a cloud server (☁️) or ZeroTier (4D).

Otherwise, compare two numbers:
- On the Pi: `curl https://api.ipify.org`, which shows your public IP.
- In your router's admin page: the **WAN / Internet IP**.

**Same number?** You can port-forward, so continue with 4B. **Different** (or the
router's WAN IP starts with `100.64`–`100.127`, `10.` or `192.168.`)? You're
behind CGNAT (common with Starlink, 4G/5G home internet, some fiber). Port
forwarding won't work. Use **4D (ZeroTier)** or a cloud server.

### 4B. Free domain name (DuckDNS)

1. Go to **[duckdns.org](https://www.duckdns.org)**, sign in, and create a
   subdomain, e.g. `mycrew` → `mycrew.duckdns.org`.
2. Copy your **token** from the top of the DuckDNS page.
3. You'll run one command on the Pi in step 5 to keep it updated automatically.

### 4C. Port forwarding

In your router: **Port forwarding** (sometimes *Virtual server*, *NAT* or
*Applications & gaming*). Forward each of these to the Pi's fixed IP from step 3:

| Port | Protocol | For | |
|---|---|---|---|
| 80 | TCP | HTTPS certificate (Let's Encrypt) | required |
| 443 | TCP | Web map, buddy share links | required |
| 8089 | TCP | ATAK / iTAK / WinTAK connection | required |
| 8443 | TCP | Data packages, plugins | required |
| 8446 | TCP | Certificate enrollment | required |
| 64738 | TCP **and** UDP | Team radio | if you want radio |
| 1935 | TCP | Drone video in (DJI Fly) | if you want video |
| 8554 | TCP | Video to ATAK | if you want video |
| 8189 | UDP | Video in web browsers | if you want video |

**Never forward 22 (SSH), 8080 or 8088.**

☁️ Cloud: open the same ports in your provider's firewall page instead.

### 4D. ZeroTier (only if you can't port-forward)

Make a free network at **[my.zerotier.com](https://my.zerotier.com)** and note
its **Network ID**. In step 6, answer **y** to "Install ZeroTier?" and enter it.
Every buddy installs the ZeroTier app, joins that network ID, and you approve
them in the ZeroTier dashboard. Use the Pi's ZeroTier IP (shown in the
dashboard) as the server address. Skip 4B/4C.

---

## 5. Download ATAK-CX onto the Pi

In your SSH session:

```
sudo apt update && sudo apt install -y git
git clone https://github.com/ryanpeh139/ATAK-CX.git
cd ATAK-CX
```

**Using DuckDNS (4B)?** Run this now, with your subdomain and token:

```
./setup/duckdns.sh mycrew YOUR-DUCKDNS-TOKEN
```

It should say `mycrew.duckdns.org now points here`.

---

## 6. Run the installer

```
./setup/install-server.sh
```

It takes **20–40 minutes on a Pi**. It prints a lot, and sometimes sits still
for a few minutes; that's normal. Here's every question it asks and what to answer:

| Question | Answer |
|---|---|
| Add a 2 GB swap file? (only on small Pis) | **Y** |
| Team name | Anything, e.g. `CX` (shown in everyone's ATAK) |
| Server domain or IP | Your DuckDNS name, e.g. `mycrew.duckdns.org` (or the ZeroTier IP) |
| *Press Enter to start* | Enter |
| Install ZeroTier? *(OpenTAKServer's question)* | **n**, unless you chose 4D |
| Install Mumble Server? *(OpenTAKServer's question)* | **n**. The radio step below does it properly. |
| Turn on the firewall? | **Y** |
| Set up the team radio? | **Y** |
| Turn on live video? | **Y** |
| Turn on emergency alerts? → Discord / Telegram | **Y**, then press Enter to skip Discord/Telegram (or paste them) |
| Turn on public-land maps? | **Y** (US only) |
| Turn on aircraft tracking? → which town? | **Y**, then e.g. `Denver, CO` or `39.74,-104.99` |
| Build elevation data for your area? → which town? | **Y**, and press Enter to reuse the aircraft town (takes a minute or two) |
| Get a free certificate for … ? | **Y** (needs ports 80/443 forwarded; you can re-run later with `./setup/enable-https.sh`) |
| Email for Let's Encrypt | Optional, just press Enter |
| Turn on the web manager? | **Y** |
| Back up every night? | **Y** |

At the end it prints your web map address and where the admin login is saved
(`~/takcx/admin.conf`; view it with `cat ~/takcx/admin.conf`).

**If it stops with an error:** copy the last 20 lines and see
[Troubleshooting](troubleshooting.md). It's safe to fix the problem and run
`./setup/install-server.sh` again; finished steps are skipped.

---

## 7. Check it works from outside

```
takcx doctor
```

Everything should say `[ok]`. Then the real test: **on your phone, turn Wi-Fi
off** (mobile data only) and open `https://mycrew.duckdns.org`. You should see
the OpenTAKServer login page with no security warning. If it doesn't load,
recheck port forwarding (4C) and DuckDNS (4B).

---

## 8. Add yourself and your buddies

Start with yourself, to test the whole flow. `--admin` also lets you log into the
web Manager:

```
takcx add ryan --role "Team Lead" --admin --share
```

It prints a private link and a QR code. Open the link on your phone and follow
the page: install ATAK, download your file, import it. Within a minute you
should be a dot on the map and see yourself in the web map.

Then everyone else:

```
takcx add bob --callsign Bobcat --color Red --share
takcx add sarah --role Medic --share
```

Text each person their link. The page walks them through Android, iPhone or
Windows, plus the radio, chat and video. Once they're connected, take the link
down: `takcx unshare bob`.

More: [Add buddies](2-add-buddies.md), including colors, roles and lost phones.

---

## 9. Extras

### The web Manager
Open `https://mycrew.duckdns.org/manage/` and log in as **ryan** (your own admin
account, not `administrator`). From there you can add people and drones, change
settings, build elevation data, upload plugins and download backups, all without
SSH. Turn on two-factor login for your account first:
[Manager guide](8-manager.md).

### Team radio (push-to-talk)
Already set up if you said yes. Buddies' pages explain it: install **Mumla**
(Android) or **Mumble** (PC/iPhone) and log in with their takcx username and
password. [Radio guide](4-radio.md)

### Drone video (DJI)
```
takcx add-drone drone1 --share
```
Open the link **on the phone or controller that runs DJI Fly**, tap **Copy
address**, then in DJI Fly: **⋯ → Transmission → Live Streaming Platforms →
RTMP**, paste, start. The team sees `drone1` in ATAK's **Video Player**.

If your drone and controller are supported by the **UAS Tool** plugin (see
Plugins below), that also puts the drone's position on the map.

### Aircraft on the map
Already on if you said yes. Change the area any time:
```
takcx aircraft on --near "Moab, UT" --radius 60
```

### Plugins, pushed to everyone's ATAK
**Official plugins (Data Sync, Vx, UAS Tool…):** make a free account at
**[tak.gov](https://tak.gov)**. In your web map (`https://mycrew.duckdns.org`,
admin login) open **Link TAK.gov Account** → **Get Link Code** → enter it at
tak.gov/register-device → **Link Account**. Then pick the ATAK version your
team uses and click **Download Plugin** on the ones you want. Everyone's ATAK
offers them automatically.

**Plugins from a file (e.g. Meshtastic):** download the APK that matches your ATAK
version from [Meshtastic's releases](https://github.com/meshtastic/ATAK-Plugin/releases),
copy it to the Pi, and:
```
takcx plugin upload ~/ATAK-Plugin-xxxx.apk
takcx plugin list
```
To copy a file from your computer to the Pi:
`scp ATAK-Plugin-xxxx.apk yourusername@takserver.local:~`

### Elevation data
Already built if you said yes. Everyone's welcome page has a download link; in
ATAK it's **Import → Local SD → the file → Zipped DTED directories**. Build a
different or bigger area any time:
```
takcx elevation --near "Moab, UT" --radius 80
```

### Emergency alerts on phones
Already on if you said yes. Everyone's welcome page shows how to subscribe in the
free **ntfy** app. Share the topic with family or base too. [Alerts guide](7-alerts.md)

### Meshtastic radios (no-signal areas)
What to buy and how to set them up: [Meshtastic gear](6-meshtastic-gear.md).

---

## Keeping it running

- **Backups** run nightly into `~/takcx-backups`. Copy them off the Pi now and
  then (`scp 'yourusername@takserver.local:takcx-backups/*' .`). They hold
  everyone's keys, so keep them private. [Backups & restore](maintenance.md)
- **Updates:** `sudo apt update && sudo apt upgrade -y` monthly;
  `cd ~/ATAK-CX && git pull` for ATAK-CX updates.
- **Power:** a small UPS or power bank with pass-through keeps it up through
  blips. The server recovers by itself after a power cut.
- **Health check any time:** `takcx doctor`

## Command cheat sheet

| Do this | Command |
|---|---|
| Add a buddy + link | `takcx add NAME --share` |
| List everyone | `takcx list` |
| Lock someone out (lost phone) | `takcx disable NAME` (undo: `takcx enable NAME`) |
| Delete someone | `takcx remove NAME` |
| New link for someone | `takcx share NAME` |
| Drone login | `takcx add-drone drone1 --share` |
| Aircraft area | `takcx aircraft on --near "Town"` |
| Push a plugin | `takcx plugin upload FILE.apk` |
| Elevation data for an area | `takcx elevation --near "Town"` |
| Rebuild everyone's files (after editing `~/takcx/team.conf`) | `takcx rebuild --all` |
| Something wrong? | `takcx doctor` |

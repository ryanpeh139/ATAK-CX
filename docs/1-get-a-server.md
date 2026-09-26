# 1. Get a server

The server is the hub everyone's app connects to. It needs to be on 24/7 and
reachable from wherever your group is. Pick one of these:

| | Cloud server (recommended) | Home server |
|---|---|---|
| Cost | ~$5–12/month | Free (hardware you have) |
| Works from anywhere | Yes | Only with port forwarding or ZeroTier |
| Setup effort | Lowest | Router settings, or everyone installs ZeroTier |
| Keeps working if your home internet or power is out | Yes | No |

## Option A: cloud server

Any provider works: Hetzner, DigitalOcean, Linode/Akamai, Vultr and so on.
Create a server with:

- **Ubuntu 24.04 LTS**
- **2 GB RAM or more** (1 GB works with the swap file the installer offers)
- The cheapest CPU and disk option is fine

Then SSH in. Most providers log you in as `root`. The installer won't run as root,
so create a normal user first:

```bash
adduser tak
usermod -aG sudo tak
su - tak
```

**Cloud firewalls:** some providers (AWS, Google Cloud, Oracle, Azure, and
optionally others) have a firewall in their web dashboard as well. Open these
TCP ports there: **80, 443, 8089, 8443, 8446**.

## Option B: home server (Raspberry Pi 4/5 or old PC)

Install Ubuntu Server or Raspberry Pi OS (64-bit) on a machine with 2 GB RAM
or more (4 GB is comfortable). The server uses about 1 GB just idling, so
**a Pi Zero / Zero 2 W or Pi 3A+ (512 MB) can't run it**, and a 1 GB Pi 3B is
too tight to rely on. The installer checks this and stops if there isn't enough memory.

Then choose how phones outside your house will reach it:

**Port forwarding (everyone just uses the app):** in your router, forward TCP
ports **80, 443, 8089, 8443, 8446** to the server's local IP, and give the
server a fixed local IP (a "DHCP reservation"). This doesn't work if your ISP
uses CGNAT, which is common on mobile and satellite internet (Starlink
included). To check: if the "WAN IP" on your router doesn't match
https://api.ipify.org, you're behind CGNAT. Use ZeroTier instead.

**ZeroTier (no router changes):** a free private network app. Make a free account
and network at https://my.zerotier.com, say **y** when the installer asks about
ZeroTier, and give it your network ID. Each buddy installs the ZeroTier app and
joins the same network ID, and you approve them in the ZeroTier dashboard. Use
the server's ZeroTier IP (e.g. `10.147.17.5`) as the server address.
Downside: everyone needs ZeroTier running on their phone.

## A free domain name (recommended)

With a domain name you get a real HTTPS certificate, so share links open without
a scary browser warning, and you can move servers later without re-sending
everyone's packages.

1. Go to https://www.duckdns.org and sign in.
2. Create a subdomain, e.g. `mycrew` → `mycrew.duckdns.org`.
3. Set its IP to your server's public IP (cloud) or your home IP (port forwarding).
4. For a home connection whose IP changes, use DuckDNS's "install" page to
   set up automatic updates on the server.

Use `mycrew.duckdns.org` when the installer asks for the server address.
Any domain you own works the same way: create an **A record** pointing at the server.

> **Changing the address later** means everyone needs a new package: edit
> `SERVER_ADDRESS` in `~/takcx/team.conf`, run `takcx rebuild --all`, and re-share.
> That's another reason to start with a domain.

## Ports reference

| Port | Used for | Open to internet? |
|---|---|---|
| 22 | SSH (your admin access) | Yes (installer keeps your current SSH port open) |
| 80, 443 | Web map, share links, HTTPS certificate renewal | Yes |
| 8089 | TAK apps (encrypted) | Yes |
| 8443 | TAK data packages / API (client certificate required) | Yes |
| 8446 | Certificate enrollment | Yes |
| 64738 (TCP+UDP) | Team radio (if you turned it on) | Optional |
| 8883 | Meshtastic gateway MQTT (see [radio guide](3-maps-offline-radio.md)) | Optional |
| 8080, 8088 | OpenTAKServer's **unencrypted** ports | **No**, keep closed |

Next: [install](../README.md#quick-start), then [add buddies](2-add-buddies.md).

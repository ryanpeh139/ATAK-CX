# 4. Team radio (push-to-talk voice)

Walkie-talkie style voice channels over the internet, running on your own
server. It uses [Mumble](https://www.mumble.info), a free, low-latency voice
system, and it's locked to your team:

- **Same logins as the map.** Everyone signs in with their takcx username and
  password. `takcx disable bob` cuts off Bob's radio as well as his map.
- **Encrypted.** Mumble encrypts both the connection and the voice.
- **Locked if something breaks.** Mumble has a long random server password
  that nobody is told. Only OpenTAKServer can let people past it, so if
  OpenTAKServer is ever down, the radio stays closed instead of open.

## Turn it on

The installer asks "Set up the team radio?". If you said no, or want to
change channels later, run:

```bash
cd ~/ATAK-CX
./setup/enable-radio.sh
```

Channels come from `RADIO_CHANNELS` in `~/takcx/team.conf`
(default `Main,Team 1,Team 2,Command`). Everyone starts in the first one.
Edit it and re-run the script to add channels (existing ones are kept).

For a **home server with port forwarding**, also forward port **64738**
(TCP *and* UDP) to the Pi. On a cloud server, open 64738 TCP+UDP in the
provider's firewall.

## Using it

Each buddy's welcome page has a Radio section with an **Open the radio** button
and step-by-step instructions. In short:

| Device | App |
|---|---|
| Android | [Mumla](https://play.google.com/store/apps/details?id=se.lublin.mumla) (free) |
| Windows / Mac / Linux | [Mumble](https://www.mumble.info/downloads/) |
| iPhone | search the App Store for "Mumble" |

Server: your server address, port **64738**, their takcx username and password.
The first time, the app asks to accept the server's certificate: accept it.

Tips:
- **Push-to-talk:** in Mumla, Settings → Audio → Transmit mode → Push to talk.
  A cheap Bluetooth PTT button or headset button can be mapped to it.
- **Channels:** everyone in the same channel hears each other. Use one per
  search team or hunting party, and **Command** for leads/base.
- **Data:** voice uses well under 1 MB per minute of talking, so it's fine on
  mobile data. It needs *some* signal, though: for no-signal areas see
  [Meshtastic](3-maps-offline-radio.md#meshtastic-long-range-off-grid) (text only).

## ATAK's voice plugin (optional)

ATAK has an official voice plugin, **Vx** (from [tak.gov](https://tak.gov)),
that puts push-to-talk inside ATAK and connects to a Mumble server like this
one. OpenTAKServer supports it. The plugin signs in with the person's
**callsign**, so for Vx users keep the callsign the same as their username
(`takcx add bob` with no `--callsign`). See [Plugins](5-plugins.md).

## If the radio won't let anyone in

```bash
takcx doctor          # checks "radio logins linked to takcx accounts"
sudo systemctl restart mumble-server     # re-links automatically
```

Behind the scenes: OpenTAKServer can only hook into Mumble when OpenTAKServer
starts, so the setup restarts OpenTAKServer every time Mumble starts (TAK
connections blip for a few seconds and reconnect on their own).

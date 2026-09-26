# 5. Plugins and extras

## Push plugins to everyone from your server

You don't have to walk each buddy through installing a plugin. Every ATAK
package takcx builds already points ATAK at your server's **plugin update
server**, so a plugin you put on the server is offered to everyone's ATAK the
next time it starts (or when they tap sync in ATAK's Plugins tool).

**Official plugins (Data Sync, Vx, UAS Tool and more), straight from TAK.gov:**
1. Make a free account at [tak.gov](https://tak.gov).
2. In the web map, logged in as admin: **Link TAK.gov Account** → **Get Link Code**,
   enter the code at tak.gov/register-device within 3 minutes, then **Link Account**.
3. Choose your team's ATAK version and flavor (ATAK-CIV), then click **Download Plugin**
   on the ones you want. Done.

**A plugin you have as a file** (e.g. the Meshtastic plugin from GitHub):
```bash
takcx plugin upload ~/ATAK-Plugin-1.x.x.apk   # reads which ATAK version it's for
takcx plugin list
takcx plugin remove com.example.plugin         # package name from the list
```
Plugins only load in the exact ATAK version they're built for, so if people use
different ATAK versions, upload a build for each.

(This is ATAK only. iTAK and WinTAK install plugins their own way.)

## ATAK plugins worth a look

Official plugins are free from [tak.gov](https://tak.gov) (free account). Some are
also on the Play Store or GitHub. Check each one's page for your ATAK version.

| Plugin | What it does | Good for |
|---|---|---|
| **Data Sync** | Shared "missions": everyone subscribed sees the same markers, shapes and files, which stay in sync | SAR incidents, planned hunts and trips |
| **Vx** | Push-to-talk voice inside ATAK, using your [team radio](4-radio.md) | Radio without switching apps |
| **Meshtastic plugin** | Positions and chat over Meshtastic LoRa radios, with no cell service needed | Backcountry, SAR ([gear guide](6-meshtastic-gear.md)) |
| **UAS Tool** | Drone video and position on the map | SAR with a drone |
| **Fire Area Survey** | Structured survey and assessment of an area (OpenTAKServer supports its data) | Damage and area assessments |

OpenTAKServer supports Data Sync and Fire Area Survey through its Mission API.
That works over your normal encrypted connection, which takcx packages already use.

## Server extras (no plugin needed)

These are OpenTAKServer features you turn on in the web UI or `~/ots/config.yml`.
Full details are in the [OpenTAKServer docs](https://docs.opentakserver.io).

**Aircraft on the map (ADS-B).** Live planes and helicopters near you, shown on
everyone's map, from the free [adsb.lol](https://adsb.lol) feed. Handy for SAR,
e.g. seeing where the helicopter is.
```bash
takcx aircraft on --near "Denver, CO"            # or --near "39.74,-104.99"
takcx aircraft on --near "Moab, UT" --radius 80  # nautical miles, max 250 (default 50)
takcx aircraft off
```
It updates every 30 seconds. Behind the scenes, OpenTAKServer sends aircraft to an
"ADS-B" group; takcx adds everyone to it (plus the normal team group, so they
still see each other). New buddies are added automatically. If someone's missing
aircraft, run `takcx aircraft sync` and have them reconnect.

**Live video.** Drones, IP cameras and phone cameras streamed to the team,
watchable in ATAK's **Video Player** and on the web map. Turn it on with
`./setup/enable-video.sh` (the installer offers it), then:
- **DJI drones:** `takcx add-drone drone1 --share` gives you a page to open on the
  phone/controller running DJI Fly, with the stream address and the steps
  (DJI Fly → Transmission → Live Streaming Platforms → RTMP). Works with most
  DJI drones from 2020 on. The **UAS Tool** plugin can also show a supported
  drone's position on the map. It supports DJI models through DJI's developer kit,
  but not controllers with a built-in screen (DJI RC, RC 2).
- **A phone's camera:** web map → **Video Streams** → **Start Streaming**, or the
  [OpenTAK ICU](https://github.com/brian7704/OpenTAK_ICU) Android app (which also
  sends your position).
- **Watching in ATAK:** Video Player → download button → pick the stream → edit
  it and enter your takcx username and password.
- Ports: 1935/tcp (streams in), 8554/tcp (to ATAK), 8189/udp (browsers).

**Ships on the map (AIS).** Vessels from [AISHub](https://www.aishub.net). Needs
an AISHub account (usually requires running your own AIS receiver). Only useful
near water.

**Meshtastic bridge.** Links a Meshtastic radio network to your server so
people on radios appear on everyone's map. See the
[radio guide](3-maps-offline-radio.md#meshtastic-long-range-off-grid).

**Device profiles.** Push settings or files to every device when it connects
(web UI → **Device Profiles**), e.g. a new map source or a standard set of
rally points.

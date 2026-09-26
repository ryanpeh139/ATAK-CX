# 5. Plugins and extras

## Push plugins to everyone from your server

You don't have to walk each buddy through installing a plugin. Every ATAK
package takcx builds already points ATAK at your server's **plugin update
server**:

1. Get the plugin's APK (see below).
2. Log into the web UI as admin → **Plugin Updates** → **Upload Plugin**.
3. The next time people open ATAK, it offers to install or update it.

(This is ATAK only. iTAK and WinTAK have their own plugin systems.)

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

**Aircraft on the map (ADS-B).** Live planes and helicopters near you from the
free [Airplanes.live](https://airplanes.live) feed, shown on everyone's map. Handy
for SAR, e.g. seeing where the helicopter is.
- In `~/ots/config.yml` set `OTS_AIRPLANES_LIVE_LAT`, `OTS_AIRPLANES_LIVE_LON`
  and `OTS_AIRPLANES_LIVE_RADIUS` (nautical miles, max 250), then
  `sudo systemctl restart opentakserver`.
- Web UI → **Scheduled Jobs** → **Airplanes.live** → **Activate**. Poll every
  minute or so, not every second.

**Live video.** Stream a phone camera, drone or IP camera to the team, and watch
it in ATAK or the web map.
- Easiest: web UI → **Video Streams** → **Start Streaming** from any phone browser.
- Or use the [OpenTAK ICU](https://github.com/brian7704/OpenTAK_ICU) Android app,
  which sends your position with the video.
- Video uses extra ports (e.g. RTSP 8554 / RTSPS 8322). Open only what you use.

**Ships on the map (AIS).** Vessels from [AISHub](https://www.aishub.net). Needs
an AISHub account (usually requires running your own AIS receiver). Only useful
near water.

**Meshtastic bridge.** Links a Meshtastic radio network to your server so
people on radios appear on everyone's map. See the
[radio guide](3-maps-offline-radio.md#meshtastic-long-range-off-grid).

**Device profiles.** Push settings or files to every device when it connects
(web UI → **Device Profiles**), e.g. a new map source or a standard set of
rally points.

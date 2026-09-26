# 3. Maps, offline use and radios

## Maps included

Every ATAK/WinTAK package comes with these map sources (in `maps/`):

| Map | Good for | Coverage |
|---|---|---|
| Esri World Imagery | Satellite photos: terrain, clearings, trails, buildings | World |
| Esri World Topo | General topo with place names | World |
| Esri World Street Map | Roads and towns | World |
| OpenTopoMap | Contour lines, trails, hiking | World |
| USGS Topo | Classic US topo quads: contours, trails, land features | US only |
| USGS Imagery + Topo | Satellite with topo overlay | US only |

In ATAK: **☰ → Maps & Favorites** (on some versions just **Maps**), then pick
one. For iTAK, the built-in maps are good, and the `-maps.zip` package can be
imported too if your iTAK version supports custom map sources.

**Add your own:** drop another ATAK map source `.xml` into `maps/`, run
`takcx rebuild --all` and have people re-import (or send them `takcx maps`, a
maps-only package with no login in it, safe to share with anyone).

## Offline maps (do this before you go)

Online maps need signal. Out in the woods or at a search site, download the
area in advance:

1. On Wi-Fi, open **Maps & Favorites** and choose a map (e.g. USGS Topo or Esri Imagery).
2. Tap the download / select-area button and draw a box around your area.
3. Pick the zoom range: more zoom means more detail, and a bigger download.
   For a hunting unit or search area, levels up to 16–17 are plenty.
4. Downloaded tiles are used automatically when there's no signal.

Be reasonable: download the area you need, not whole states. OpenTopoMap in
particular is run by volunteers, so use USGS/Esri for big downloads.

For large areas you can also make an **MBTiles** or **GeoPackage** file on a computer
(e.g. with [MOBAC](https://mobac.sourceforge.io/) or QGIS) and copy it into the
`atak/imagery` folder on the phone.

**Elevation:** ATAK's elevation, line-of-sight and slope tools need elevation
data (DTED). Without it they're limited. Search "ATAK DTED" for how to add it
for your region.

## When there's no cell signal

Your server is out on the internet, so with no internet nobody can reach it.
You still have options:

### Same Wi-Fi or hotspot (no server needed)

ATAK phones on the **same local network** find each other automatically and
share positions, chat and markers. That's ATAK's built-in "mesh" mode. So one
phone or a travel router running a Wi-Fi hotspot at camp (it doesn't need
internet) is enough for everyone connected to it to see each other. When
internet comes back, the server connection picks back up.

### Meshtastic (long-range, off-grid)

[Meshtastic](https://meshtastic.org) radios are cheap LoRa devices that pair
with your phone over Bluetooth and relay messages for miles, with no cell
network or license needed. With the **Meshtastic ATAK plugin**, ATAK sends
positions (PLI) and chat over the radios, which fits hunting, backcountry and SAR
well. See Meshtastic's docs for the ATAK plugin setup.

**Bridge the mesh to your server** (optional): OpenTAKServer can link a
Meshtastic network to everyone on the server, so people on radios show up on
the server map and the other way round. It needs one Meshtastic node with
internet (Wi-Fi) as a gateway:

1. In `~/ots/config.yml` set `OTS_ENABLE_MESHTASTIC: true`, then
   `sudo systemctl restart opentakserver`.
2. Open the MQTT port: `sudo ufw allow 8883/tcp`.
3. Configure the gateway node's MQTT per the
   [OpenTAKServer Meshtastic guide](https://docs.opentakserver.io/meshtastic.html)
   (server = your server address, a takcx username/password, TLS on).

Only positions and chat cross over, not markers or data packages, to keep
the radio channel from getting flooded.

### Ham radio: know the rule

If you're licensed and thinking of running TAK over amateur frequencies:
amateur rules (e.g. FCC Part 97 in the US) **prohibit encryption** meant to hide
the meaning of messages. TAK's server connection is always encrypted, so **don't
carry it over ham bands.** Meshtastic's licensed ("ham") mode turns encryption off
and lets you run more power, and it's fine for the unencrypted mesh features. On
unlicensed Meshtastic (the default), encryption is allowed and on.

## Team radio and chat

**Chat** is built into ATAK, iTAK and WinTAK, so there's nothing to set up. It goes
through your server, encrypted: "All Chat Rooms" for everyone, a room per team
color, or one-to-one by tapping someone on the map. See each buddy's welcome page.

**Radio** is push-to-talk voice on a Mumble server, set up by
`setup/enable-radio.sh` (the installer offers it). See
[Team radio](4-radio.md) for how it works and how to use it.

## Handy built-in ATAK tools

- **Emergency alert:** sends an alert and your location to everyone. Find it
  under **Alert** in the tools menu. Try it once with the group so everyone
  knows what it looks like.
- **Chat:** team-wide or one-to-one, with your position attached.
- **Drawing tools:** mark search sectors, property lines, stands, rally points.
  Shapes and markers sync to everyone connected.
- **Routes:** plan a route, share it, and navigate with bearing and distance.
- **Range & bearing:** tap-and-drag distance and direction between any two points.
- **Data packages:** bundle markers, shapes, routes and photos for a trip or
  search and share them with everyone.

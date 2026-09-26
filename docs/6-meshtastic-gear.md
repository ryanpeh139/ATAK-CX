# 6. Meshtastic gear (off-grid radios)

[Meshtastic](https://meshtastic.org) nodes are small LoRa radios that relay
messages between each other for miles, with no cell service, internet or
license needed. Paired with ATAK, they carry **positions and chat** when you're
out of signal. Markers, photos and data packages stay on the normal server
connection, because the radio link is too slow for them.

## How it fits together

```
 your phone ── Bluetooth ── your node  ))) LoRa mesh (((  buddy's node ── Bluetooth ── buddy's phone
 (ATAK + Meshtastic plugin                                        (ATAK + Meshtastic plugin
  + Meshtastic app)                                                + Meshtastic app)
```

Each person needs three things:
1. **A node** (see below), paired to their phone.
2. **The Meshtastic app** ([Android](https://play.google.com/store/apps/details?id=com.geeksville.mesh)),
   left running in the background.
3. **The Meshtastic ATAK plugin**, from its
   [GitHub releases](https://github.com/meshtastic/ATAK-Plugin/releases). Pick the
   build that matches your ATAK version exactly. To skip installing it on every
   phone, upload it once to your server's plugin update server
   ([Plugins](5-plugins.md)) and everyone's ATAK offers it automatically.

When it's working, a **green Meshtastic icon** shows in ATAK's bottom-right
corner (red means the plugin can't reach the Meshtastic app). See Meshtastic's
[ATAK plugin guide](https://meshtastic.org/docs/software/integrations/integrations-atak-plugin/)
and [TAK integration guide](https://meshtastic.org/docs/software/android/user/tak/).

> **Buy the right frequency for your country:** 915 MHz in the US/Canada/Australia,
> 868 MHz in Europe/UK, and so on. Most listings make you choose.

## Recommended nodes

For carrying all day, prefer **nRF52840**-based nodes (all the picks below
except the Station G2). They use much less power than ESP32 boards, often
40–60% longer runtime.

### One per person (clips to your kit, pairs with your phone)

| Node | Why | Link |
|---|---|---|
| **Seeed SenseCAP T1000-E** | Credit-card size, GPS, IP65, ~$40. The easy default. | [Seeed](https://www.seeedstudio.com/SenseCAP-Card-Tracker-T1000-E-for-Meshtastic-p-5913.html) · [setup wiki](https://wiki.seeedstudio.com/t1000_e_tracker_meshtastic/) |
| **RAK WisMesh Tag** | Like the T1000-E but tougher: IP66, bigger 1000 mAh battery, real button | [RAK store](https://store.rakwireless.com/products/wismesh-tag-meshtastic-gps-lora-tracker-ip66) |
| **muzi works R1 Neo** | Rugged: aluminium base, gasketed, IP68 USB-C, 1500 mAh, GPS. ~$89 | [muzi works](https://muzi.works/products/r1-neo-complete-meshtastic-device) |
| **RAK WisMesh Pocket V2** | Pocket unit with a screen and GPS, so you can read messages on it | [RAK store](https://store.rakwireless.com/products/wismesh-pocket) |
| **LILYGO T-Echo** | E-ink screen (readable in sun, very low power), GPS | [Meshtastic device page](https://meshtastic.org/docs/hardware/devices/lilygo/) |

### Trackers with no phone needed (vehicles, dogs, gear, base)

Set the node's role to **TAK_TRACKER** and it broadcasts its GPS position to the
team's ATAK maps on its own. The **T1000-E** and **WisMesh Tag** above suit this well.

### Messaging without a phone

**RAK WisMesh TAP V2**: touchscreen, on-screen keyboard, GPS, offline maps, and
a big 3200 mAh battery. Good for a base or command post, or someone who doesn't
carry a phone. [RAK store](https://store.rakwireless.com/products/meshtastic-touch-client-wismesh-tap-v2-sx1262)

### Extending range (relays)

Put a relay high up, like a ridge, a tree or a vehicle roof, and everyone's range jumps.

| Node | Use | Link |
|---|---|---|
| **RAK WisMesh Repeater Mini** | Portable solar relay for a camp, trailhead or search area | [RAK store](https://store.rakwireless.com/products/wismesh-meshtastic-solar-repeater-mini) |
| **RAK WisMesh Repeater** | Permanent solar relay for a property, farm or home area | [RAK store](https://store.rakwireless.com/products/wismesh-meshtastic-solar-repeater) |
| **B&Q Station G2** | High-power base station, mainly for **licensed hams**. In ham mode encryption is off, so don't send TAK traffic that way ([why](3-maps-offline-radio.md#ham-radio-know-the-rule)) | [Meshtastic device list](https://meshtastic.org/docs/hardware/devices/) |

### Bridging the mesh to your server (optional)

To make people on radios show up on the **server** map (and the reverse), you
need one node with **Wi-Fi** at home or base as a gateway, for example RAK's
[WisMesh Wi-Fi MQTT Gateway](https://store.rakwireless.com/products/wismesh-wifi-gateway)
or any ESP32-based node with Wi-Fi. Setup is in the
[radio guide](3-maps-offline-radio.md#meshtastic-long-range-off-grid).

## Setting up a node (once per node, about 10 minutes)

1. Update the firmware at [flasher.meshtastic.org](https://flasher.meshtastic.org)
   (Chrome/Edge, over USB).
2. Pair it in the Meshtastic app and set the **Region** (e.g. `US`). Nothing
   transmits until you do.
3. **Settings → Device → Role:** `TAK` for a node paired with someone's ATAK
   phone, `TAK_TRACKER` for a standalone tracker.
4. **Same channel for the whole team.** Set up one node's primary channel
   (name + key), then share its QR code from the app. Everyone else scans it,
   so everyone's radio traffic is encrypted with your team's key.
5. On the phone: Meshtastic app running, ATAK open, green Meshtastic icon.
   Test by walking out of Wi-Fi/cell range together.

## Good to know

- **Range:** handheld to handheld is roughly 1–5 km in hilly or wooded terrain,
  much more line-of-sight. Every relay you add extends it.
- **Keep it light:** only positions and chat go over the mesh, with
  positions every few minutes. That's the right trade-off for a slow,
  shared radio channel.
- **iPhone users:** the Meshtastic ATAK plugin is ATAK-only. iPhone users can
  still use the Meshtastic iOS app with the same nodes and channel for chat
  and positions.

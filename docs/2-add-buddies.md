# 2. Add buddies

Everything here runs on the server, as the user you installed with.

## Add someone

```bash
takcx add bob
```

That creates Bob's account, gives him his own certificate and builds everything
in `~/takcx/buddies/bob/`:

| File | For |
|---|---|
| `CX-bob-ATAK.zip` | Android (ATAK) **and** Windows (WinTAK) |
| `CX-bob-iTAK.zip` | iPhone / iPad (iTAK) |
| `CX-maps.zip` | Maps only (already included in the ATAK zip) |
| `index.html` | Step-by-step page for Bob |
| `credentials.txt` | Bob's username/password for the web map and team radio |

### Options

```bash
takcx add bob --callsign Bobcat --color Red --role Medic
takcx add sarah --role "Team Lead" --admin     # --admin: can also use the web admin panel
```

- **Callsign:** the name on the map. Defaults to the username.
- **Team colors:** White, Yellow, Orange, Magenta, Red, Maroon, Purple, Dark Blue,
  Blue, Cyan, Teal, Green, Dark Green, Brown
- **Roles:** Team Member, Team Lead, HQ, Sniper, Medic, Forward Observer, RTO, K9

Set the defaults for everyone in `~/takcx/team.conf` (`DEFAULT_TEAM_COLOR`,
`DEFAULT_ROLE`, `COORD_FORMAT`).

Some ways to use colors:
- **SAR:** one color per search team, **Team Lead** for team leaders, **HQ** for
  base/incident command, **Medic** for medical.
- **Hunting / hiking:** a color per party or vehicle, so you can tell at a glance
  who's with whom.

## Get it to them

**Easiest: a private link.**

```bash
takcx share bob          # or add --share when you create them
```

This prints a link like `https://mycrew.duckdns.org/join/Xy3.../index.html`
plus a QR code in your terminal. Text the link to Bob. On his phone, the page
puts his device's instructions first. Once he's connected, take it down:

```bash
takcx unshare bob
```

Treat the link like a password: anyone who has it can download Bob's login.
Without HTTPS set up (see [server guide](1-get-a-server.md#a-free-domain-name-recommended)),
browsers will show a certificate warning first.

**Or send the file directly** over Signal, WhatsApp, email or AirDrop. The zip
files are in `~/takcx/buddies/bob/`. To copy them to your computer:

```bash
scp tak@your-server:takcx/buddies/bob/*.zip .
```

## What your buddy does

The page walks them through it, but in short:

- **Android:** install ATAK-CIV from the Play Store → ☰ → **Import** → **Local SD**
  → pick the ATAK zip. The server icon goes green.
- **iPhone:** install iTAK → Settings → Network → Servers → **+** →
  **Upload Server Package** → pick the iTAK zip. Then set callsign and team color
  in iTAK settings (iTAK doesn't take those from the package).
- **Windows:** install WinTAK-CIV (tak.gov) → drag the ATAK zip onto the map.

## Lost phone, or someone leaves

```bash
takcx disable bob     # locked out of map, radio, video and web right away
                      # undo with: takcx enable bob (restores his password)
takcx remove bob      # gone for good
```

Both also drop live connections (the server's TAK listener restarts, and
everyone else reconnects on their own within seconds). If Bob gets a new
phone, `takcx enable bob` and send him the same package again.

## Changing things later

Edit `~/takcx/team.conf` or the files in `maps/`, then:

```bash
takcx rebuild --all                    # everyone
takcx rebuild bob --color Green        # one person, with a change
```

Active share links update automatically. People who already joined need to
import the new package to pick up the changes (re-importing replaces the old one).

## The web map

`https://your-server/` shows everyone live in a browser, which is handy for
whoever's running base. Log in with the username and password from that
person's `credentials.txt` (also shown on their share page), or with the admin
login in `~/takcx/admin.conf`. The admin panel also has data packages, device
profiles (push settings to every device when it connects), groups/channels,
video streams and more. See the
[OpenTAKServer docs](https://docs.opentakserver.io).

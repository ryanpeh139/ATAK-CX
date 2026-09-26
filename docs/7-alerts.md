# 7. Emergency alerts to phones

When anyone triggers an emergency in ATAK, iTAK or WinTAK (**911 Alert**, **Ring
The Bell**, **Troops In Contact**, **Geo-fence Breached**...), everyone
subscribed gets a **loud push notification with a map link to where it
happened**, even if ATAK is closed. When the alert is cancelled, a follow-up
says so.

It's good for:
- team members whose ATAK is closed or phone is in a pocket
- **family at home** or a base contact who doesn't use ATAK at all
- a Discord or Telegram group chat

## Turn it on

The installer asks. To do it later, or to add Discord/Telegram:

```bash
cd ~/ATAK-CX
./setup/enable-alerts.sh
```

It creates a private, unguessable ntfy topic (e.g. `cx-alerts-3f9a0c…`), sends a
test notification, and adds sign-up steps to everyone's welcome page.

## Getting alerts on a phone

1. Install the free **ntfy** app:
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) ·
   [iPhone](https://apps.apple.com/app/ntfy/id1625396347)
2. Tap **+**, subscribe to your team's topic (it's in `~/takcx/team.conf` as
   `NTFY_TOPIC`, and on every welcome page).
3. Allow notifications. On Android you can also let the topic override
   Do Not Disturb (ntfy → topic → settings).

**Keep the topic private.** On the public ntfy.sh server, the topic name is the
only thing protecting it, and alerts include locations. If it leaks, delete
`NTFY_TOPIC` from `~/takcx/team.conf`, re-run `./setup/enable-alerts.sh` to get
a new one, and run `takcx rebuild --all`.

## Discord and Telegram (optional)

**Discord:** in your server, **Server Settings → Integrations → Webhooks →
New Webhook**, pick the channel, **Copy Webhook URL**, and paste it when
`enable-alerts.sh` asks.

**Telegram:**
1. Message **@BotFather** → `/newbot` → copy the token it gives you.
2. Add your new bot to your group chat and send any message in the group.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and find
   `"chat":{"id":-100…}`. That number (including the minus sign) is the chat ID.
4. Paste both when `enable-alerts.sh` asks.

## How it works

A small service, `takcx-alerts`, listens to everything passing through
OpenTAKServer. When it sees an emergency message it sends one notification
per alert. ATAK keeps re-sending an active alert, so you get a reminder at
most every 10 minutes, not a flood. Check it with `takcx doctor`, or see its log:

```bash
journalctl -u takcx-alerts -n 50
```

Send a test notification any time:

```bash
~/.opentakserver_venv/bin/python ~/ATAK-CX/takcx/alert_bridge.py --test
```

**Self-hosting ntfy:** to keep alert contents off the public ntfy.sh server,
run your own ntfy and set `NTFY_SERVER="https://your-ntfy"` in `~/takcx/team.conf`,
then `sudo systemctl restart takcx-alerts`.

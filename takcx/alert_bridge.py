#!/usr/bin/env python3
"""Forward ATAK emergency alerts to people's phones.

When someone triggers an emergency in ATAK/iTAK/WinTAK (911 Alert, Ring The
Bell, Troops In Contact, Geo-fence Breached...), this sends a push notification
through ntfy (and optionally Discord and Telegram) with who, what and a map link,
and another one when it's cancelled.

It listens to OpenTAKServer's "firehose" (every CoT message on the server, via
RabbitMQ), so it runs with OpenTAKServer's Python, which has pika:
  ~/.opentakserver_venv/bin/python takcx/alert_bridge.py          # run
  ~/.opentakserver_venv/bin/python takcx/alert_bridge.py --test   # send a test alert

Settings live in ~/takcx/team.conf (see setup/enable-alerts.sh).
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

TAKCX_HOME = os.environ.get("TAKCX_HOME", os.path.expanduser("~/takcx"))
OTS_DATA_FOLDER = os.environ.get("OTS_DATA_FOLDER", os.path.expanduser("~/ots"))
REMIND_AFTER = 10 * 60  # ATAK repeats an active alert; re-notify at most this often (seconds)


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def read_team():
    conf = {}
    path = os.path.join(TAKCX_HOME, "team.conf")
    if os.path.exists(path):
        for line in open(path):
            m = re.match(r'^\s*([A-Z_][A-Z0-9_]*)=(.*)$', line)
            if m:
                v = m.group(2).strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                conf[m.group(1)] = v
    return conf


def read_rabbit():
    conf = {"OTS_RABBITMQ_SERVER_ADDRESS": "127.0.0.1", "OTS_RABBITMQ_USERNAME": "guest",
            "OTS_RABBITMQ_PASSWORD": "guest"}
    path = os.path.join(OTS_DATA_FOLDER, "config.yml")
    if os.path.exists(path):
        for line in open(path):
            m = re.match(r"^([A-Z_][A-Z0-9_]*):\s*(.*?)\s*$", line)
            if m and m.group(1) in conf and m.group(2):
                conf[m.group(1)] = m.group(2).strip("'\"")
    return conf


def post(url, data, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def notify(team, title, message, map_url=None, urgent=True):
    """Send to every configured channel. One failing never stops the others."""
    sent = []
    topic = team.get("NTFY_TOPIC")
    if topic:
        server = team.get("NTFY_SERVER") or "https://ntfy.sh"
        headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore"),
                   "Priority": "urgent" if urgent else "default",
                   "Tags": "rotating_light" if urgent else "white_check_mark"}
        if map_url:
            headers["Click"] = map_url
            # ntfy's action syntax is comma-separated, so the URL can't contain raw commas.
            headers["Actions"] = f"view, Open map, {map_url.replace(',', '%2C')}"
        try:
            post(f"{server.rstrip('/')}/{topic}", message.encode(), headers)
            sent.append("ntfy")
        except Exception as e:
            log(f"ntfy failed: {e}")
    text = f"{title}\n{message}" + (f"\n{map_url}" if map_url else "")
    if team.get("DISCORD_WEBHOOK"):
        try:
            post(team["DISCORD_WEBHOOK"], json.dumps({"content": text[:1900]}).encode(),
                 {"Content-Type": "application/json", "User-Agent": "ATAK-CX alerts"})
            sent.append("discord")
        except Exception as e:
            log(f"Discord failed: {e}")
    if team.get("TELEGRAM_BOT_TOKEN") and team.get("TELEGRAM_CHAT_ID"):
        try:
            post(f"https://api.telegram.org/bot{team['TELEGRAM_BOT_TOKEN']}/sendMessage",
                 json.dumps({"chat_id": team["TELEGRAM_CHAT_ID"], "text": text}).encode(),
                 {"Content-Type": "application/json"})
            sent.append("telegram")
        except Exception as e:
            log(f"Telegram failed: {e}")
    return sent


def parse_emergency(cot):
    """Return a dict for emergency / cancel CoTs, else None."""
    if "<emergency" not in cot:
        return None
    try:
        event = ET.fromstring(cot)
    except ET.ParseError:
        return None
    emergency = event.find("./detail/emergency")
    if emergency is None:
        return None
    point = event.find("point")
    contact = event.find("./detail/contact")
    link = event.find("./detail/link")
    who = (emergency.text or "").strip() or (
        contact.get("callsign", "").removesuffix("-Alert") if contact is not None else "") or "Someone"
    return {
        "who": who,
        "sender": link.get("uid") if link is not None and link.get("uid") else event.get("uid", who),
        "kind": emergency.get("type") or "Emergency",
        "cancel": emergency.get("cancel", "").lower() == "true" or event.get("type") == "b-a-o-can",
        "lat": point.get("lat") if point is not None else None,
        "lon": point.get("lon") if point is not None else None,
    }


class Bridge:
    def __init__(self, team):
        self.team = team
        self.active = {}  # sender -> last notified time

    def handle(self, cot):
        alert = parse_emergency(cot)
        if not alert:
            return
        team_name = self.team.get("TEAM_NAME", "Team")
        sender = alert["sender"]
        map_url = None
        if alert["lat"] and alert["lon"] and alert["lat"] not in ("0", "0.0"):
            map_url = ("https://www.google.com/maps/search/?api=1&query="
                       + urllib.parse.quote(f"{alert['lat']},{alert['lon']}"))
        if alert["cancel"]:
            if self.active.pop(sender, None) is not None:
                sent = notify(self.team, f"{team_name}: alert cancelled",
                              f"{alert['who']} cancelled their emergency alert.", urgent=False)
                log(f"cancel from {alert['who']} -> {sent}")
            return
        last = self.active.get(sender)
        if last and time.time() - last < REMIND_AFTER:
            return  # ATAK keeps re-sending an active alert; don't spam
        self.active[sender] = time.time()
        prefix = "STILL ACTIVE: " if last else ""
        where = f"at {float(alert['lat']):.5f}, {float(alert['lon']):.5f}" if map_url else "(no location)"
        sent = notify(self.team, f"{prefix}{alert['kind']}: {alert['who']}",
                      f"{alert['who']} triggered '{alert['kind']}' in {team_name} {where}.", map_url)
        log(f"{alert['kind']} from {alert['who']} -> {sent}")


def run():
    import pika  # from OpenTAKServer's Python

    rabbit = read_rabbit()
    while True:
        team = read_team()
        if not (team.get("NTFY_TOPIC") or team.get("DISCORD_WEBHOOK") or team.get("TELEGRAM_BOT_TOKEN")):
            log("No notification channel configured in team.conf; run setup/enable-alerts.sh")
            time.sleep(60)
            continue
        bridge = Bridge(team)
        try:
            params = pika.ConnectionParameters(
                host=rabbit["OTS_RABBITMQ_SERVER_ADDRESS"],
                credentials=pika.PlainCredentials(rabbit["OTS_RABBITMQ_USERNAME"],
                                                  rabbit["OTS_RABBITMQ_PASSWORD"]),
                heartbeat=60)
            conn = pika.BlockingConnection(params)
            channel = conn.channel()
            channel.exchange_declare("firehose", durable=True, exchange_type="fanout")
            queue = channel.queue_declare("", exclusive=True, auto_delete=True).method.queue
            channel.queue_bind(queue=queue, exchange="firehose")

            def on_message(ch, method, props, body):
                try:
                    bridge.handle(json.loads(body).get("cot", ""))
                except Exception as e:
                    log(f"couldn't handle a message: {e}")

            channel.basic_consume(queue=queue, on_message_callback=on_message, auto_ack=True)
            log("Listening for emergency alerts")
            channel.start_consuming()
        except Exception as e:
            log(f"RabbitMQ connection problem ({e}); retrying in 10 s")
            time.sleep(10)


def main():
    if "--test" in sys.argv:
        team = read_team()
        sent = notify(team, f"{team.get('TEAM_NAME', 'Team')}: test alert",
                      "If you can read this, emergency alerts will reach this phone.",
                      "https://www.google.com/maps/search/?api=1&query=0%2C0", urgent=False)
        print("Sent via: " + (", ".join(sent) if sent else "nothing (check team.conf / network)"))
        return 0 if sent else 1
    run()


if __name__ == "__main__":
    sys.exit(main())

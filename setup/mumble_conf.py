#!/usr/bin/env python3
"""Apply ATAK-CX's settings to a Mumble server ini file (Mumble 1.3 or 1.5).

Usage: mumble_conf.py INI TEAM_NAME

- Turns on Ice on localhost only, so OpenTAKServer can check radio logins
  against its own accounts (no Ice secret, like OpenTAKServer's installer).
- Sets a long random server password that nobody is told. Logins approved by
  OpenTAKServer skip it, so if OpenTAKServer is ever down the radio stays
  locked instead of letting anyone in.
- Names the server after the team, sets a welcome message, and makes everyone
  start in the default channel.
"""

import html
import re
import secrets
import shutil
import sys


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    path, team = sys.argv[1], sys.argv[2]
    team = re.sub(r'["\\<>]', "", team).strip() or "Team"

    settings = {
        "ice": '"tcp -h 127.0.0.1 -p 6502"',
        "serverpassword": secrets.token_hex(24),
        "registerName": f'"{team} Radio"',
        # Always start in the default channel (set by radio_channels.py). With
        # remembering on, OpenTAKServer-checked users land in the top level.
        "rememberchannel": "false",
        # No "channel listeners" (Mumble 1.4+): Mumla can't show who's listening in, so the
        # server warns every Mumla user. Turning it off means nobody listens in unseen.
        "listenersperchannel": "0",
        "listenersperuser": "0",
        "welcometext": f'"<br />Welcome to the <b>{html.escape(team)}</b> radio. Hold to talk, let go to listen.<br />"',
    }
    disable = ["icesecretread", "icesecretwrite"]

    lines = open(path).read().splitlines()
    # Only touch the top-level (general) part; later [sections] like [Ice] stay as they are.
    end = next((i for i, l in enumerate(lines) if re.match(r"^\s*\[.+\]\s*$", l)), len(lines))
    general, rest = lines[:end], lines[end:]

    keys = "|".join(map(re.escape, list(settings) + disable))
    marker = "; --- ATAK-CX radio settings (setup/enable-radio.sh) ---"
    kept = []
    for line in general:
        if line == marker:
            continue
        m = re.match(rf"^\s*(;?)\s*({keys})\s*=", line)
        if m and not m.group(1):
            # Active line for a key we manage: drop it (ours go at the top).
            continue
        kept.append(line)

    block = [marker] + [f"{k}={v}" for k, v in settings.items()] + [marker, ""]
    shutil.copy(path, path + ".takcx-bak")
    with open(path, "w") as f:
        f.write("\n".join(block + kept + rest) + "\n")
    print(f"Updated {path}")


if __name__ == "__main__":
    main()

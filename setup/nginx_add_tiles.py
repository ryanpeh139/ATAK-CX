#!/usr/bin/env python3
"""Add the ATAK-CX /tiles/ location to OpenTAKServer's port 443 nginx site.

Usage: nginx_add_tiles.py /etc/nginx/sites-available/ots_https [PORT]
Safe to run again: it does nothing if the location is already there.
"""

import re
import shutil
import sys

MARKER = "# ATAK-CX public-land map tiles (setup/enable-publicland.sh)"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    port = sys.argv[2] if len(sys.argv) > 2 else "8095"
    text = open(path).read()
    if MARKER in text:
        print(f"{path}: tiles location already present")
        return

    # Find the top-level server block that listens on 443.
    depth, start = 0, None
    for m in re.finditer(r"[{}]", text):
        if m.group() == "{":
            if depth == 0:
                start = text.rfind("\n", 0, m.start()) + 1
            depth += 1
            continue
        depth -= 1
        if depth == 0 and start is not None:
            block = text[start:m.end()]
            if re.search(r"^\s*listen\s+443\s+ssl", block, flags=re.M):
                location = (f"\n    {MARKER}\n    location /tiles/ {{\n"
                            f"        proxy_pass http://127.0.0.1:{port};\n"
                            f"        proxy_read_timeout 60s;\n    }}\n")
                close = m.start()  # insert just before the block's closing brace
                shutil.copy(path, path + ".takcx-bak")
                with open(path, "w") as f:
                    f.write(text[:close] + location + text[close:])
                print(f"{path}: added /tiles/ to the port 443 site")
                return
    sys.exit(f"{path}: no port 443 server block found")


if __name__ == "__main__":
    main()

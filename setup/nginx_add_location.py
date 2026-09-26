#!/usr/bin/env python3
"""Add an ATAK-CX location (reverse proxy to a local service) to OpenTAKServer's
port 443 nginx site.

Usage: nginx_add_location.py SITE_FILE PATH PORT [MAX_BODY]
  e.g. nginx_add_location.py /etc/nginx/sites-available/ots_https /manage/ 8096 300M

Safe to run again: if that location already exists, nothing changes.
"""

import re
import shutil
import sys


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    site, path, port = sys.argv[1], sys.argv[2], sys.argv[3]
    max_body = sys.argv[4] if len(sys.argv) > 4 else None
    if not re.fullmatch(r"/[a-z0-9-]+/", path) or not port.isdigit():
        sys.exit("PATH must look like /name/ and PORT must be a number")
    text = open(site).read()
    if re.search(rf"location\s+{re.escape(path)}\s*\{{", text):
        print(f"{site}: {path} is already there")
        return

    bare = path.rstrip("/")
    block = (f"\n    # ATAK-CX {path} (added by setup/nginx_add_location.py)\n"
             f"    location = {bare} {{ return 301 {path}; }}\n"
             f"    location {path} {{\n"
             f"        proxy_pass http://127.0.0.1:{port};\n"
             f"        proxy_http_version 1.1;\n"
             f"        proxy_set_header Host $host;\n"
             f"        proxy_set_header X-Real-IP $remote_addr;\n"
             f"        proxy_set_header X-Forwarded-Proto $scheme;\n"
             f"        proxy_read_timeout 120s;\n"
             + (f"        client_max_body_size {max_body};\n" if max_body else "")
             + "    }\n")

    # Find the top-level server block that listens on 443 and insert before its closing brace.
    depth, start = 0, None
    for m in re.finditer(r"[{}]", text):
        if m.group() == "{":
            if depth == 0:
                start = text.rfind("\n", 0, m.start()) + 1
            depth += 1
            continue
        depth -= 1
        if depth == 0 and start is not None:
            if re.search(r"^\s*listen\s+443\s+ssl", text[start:m.end()], flags=re.M):
                shutil.copy(site, site + ".takcx-bak")
                with open(site, "w") as f:
                    f.write(text[:m.start()] + block + text[m.start():])
                print(f"{site}: added {path} -> 127.0.0.1:{port}")
                return
    sys.exit(f"{site}: no port 443 server block found")


if __name__ == "__main__":
    main()

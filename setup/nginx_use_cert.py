#!/usr/bin/env python3
"""Swap OpenTAKServer's nginx configs over to a Let's Encrypt certificate.

Per OpenTAKServer's docs: only the port 443 server block in ots_https and the
enrollment site on 8446 change. The 8443 block must keep the server's own
certificate, because ATAK pins it through the truststore in each package.

Usage: nginx_use_cert.py DOMAIN FILE [FILE...]
"""

import re
import shutil
import sys


def top_level_blocks(text):
    """Yield (start, end) spans of each top-level `server { ... }` block."""
    depth, start = 0, None
    for match in re.finditer(r"[{}]", text):
        if match.group() == "{":
            if depth == 0:
                start = text.rfind("\n", 0, match.start()) + 1
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                yield start, match.end()


def swap_certs(block, cert, key):
    block = re.sub(r"(^\s*ssl_certificate\s+)[^;]+;", rf"\g<1>{cert};", block, flags=re.M)
    return re.sub(r"(^\s*ssl_certificate_key\s+)[^;]+;", rf"\g<1>{key};", block, flags=re.M)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    domain = sys.argv[1]
    cert = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    key = f"/etc/letsencrypt/live/{domain}/privkey.pem"

    for path in sys.argv[2:]:
        text = open(path).read()
        changed, out, last = 0, [], 0
        for start, end in top_level_blocks(text):
            block = text[start:end]
            # 443 only in ots_https; the enrollment site has a single 8446 block.
            if re.search(r"^\s*listen\s+(443|8446)\s+ssl", block, flags=re.M):
                block = swap_certs(block, cert, key)
                changed += 1
            out.append(text[last:start] + block)
            last = end
        out.append(text[last:])
        if not changed:
            sys.exit(f"{path}: no port 443/8446 server block found, nothing changed")
        shutil.copy(path, path + ".takcx-bak")
        with open(path, "w") as f:
            f.write("".join(out))
        print(f"{path}: updated {changed} server block(s)")


if __name__ == "__main__":
    main()

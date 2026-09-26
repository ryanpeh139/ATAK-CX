#!/usr/bin/env python3
"""Public-land map tiles for ATAK: US land ownership blended over topo or imagery.

ATAK shows one map source at a time, and the BLM land-ownership map is an
overlay (public land tinted, private land clear). So this blends it onto a base
map on the fly and serves ordinary map tiles:

  /tiles/publicland-topo/{z}/{x}/{y}.jpg      USGS Topo + land ownership
  /tiles/publicland-imagery/{z}/{x}/{y}.jpg   USGS Imagery + land ownership

All sources are US federal, public-domain services. Tiles are cached on disk so
repeat views and ATAK's offline downloads don't hammer them.

Runs with OpenTAKServer's Python (it has Pillow), on 127.0.0.1 only; nginx
serves it at https://<server>/tiles/ (see setup/enable-publicland.sh).
"""

import io
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

PORT = int(os.environ.get("TAKCX_TILES_PORT", "8095"))
CACHE_DIR = os.environ.get("TAKCX_TILE_CACHE", os.path.expanduser("~/takcx/tile-cache"))
CACHE_MAX_BYTES = int(float(os.environ.get("TAKCX_TILE_CACHE_GB", "2")) * 1024 ** 3)
CACHE_DAYS = 30
OVERLAY_OPACITY = 0.45
USER_AGENT = "ATAK-CX public-land tile blender (+https://github.com/ryanpeh139/ATAK-CX)"

NATIONAL_MAP = "https://basemap.nationalmap.gov/arcgis/rest/services"
OWNERSHIP = ("https://gis.blm.gov/arcgis/rest/services/lands/"
             "BLM_Natl_SMA_Cached_without_PriUnk/MapServer/tile/{z}/{y}/{x}")
OWNERSHIP_MAX_Z = 14  # BLM's cache stops here; deeper tiles are enlarged from z14
LAYERS = {
    "publicland-topo": (f"{NATIONAL_MAP}/USGSTopo/MapServer/tile/{{z}}/{{y}}/{{x}}", 16),
    "publicland-imagery": (f"{NATIONAL_MAP}/USGSImageryOnly/MapServer/tile/{{z}}/{{y}}/{{x}}", 16),
}
PATH_RE = re.compile(r"^/tiles/([a-z-]+)/(\d{1,2})/(\d{1,7})/(\d{1,7})\.(?:jpg|png)$")

_writes = 0
_lock = threading.Lock()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def ownership_tile(z, x, y):
    """The land-ownership overlay for this tile, enlarged from z14 when deeper."""
    if z <= OWNERSHIP_MAX_Z:
        data = fetch(OWNERSHIP.format(z=z, x=x, y=y))
        return Image.open(io.BytesIO(data)).convert("RGBA") if data else None
    dz = z - OWNERSHIP_MAX_Z
    ax, ay = x >> dz, y >> dz
    data = fetch(OWNERSHIP.format(z=OWNERSHIP_MAX_Z, x=ax, y=ay))
    if not data:
        return None
    size = 256 >> dz
    ox, oy = (x - (ax << dz)) * size, (y - (ay << dz)) * size
    parent = Image.open(io.BytesIO(data)).convert("RGBA")
    return parent.crop((ox, oy, ox + size, oy + size)).resize((256, 256), Image.NEAREST)


def render(layer, z, x, y):
    base_url, _ = LAYERS[layer]
    base_data = fetch(base_url.format(z=z, x=x, y=y))
    if not base_data:
        return None
    base = Image.open(io.BytesIO(base_data)).convert("RGBA")
    overlay = ownership_tile(z, x, y)
    if overlay is not None:
        overlay.putalpha(overlay.getchannel("A").point(lambda a: int(a * OVERLAY_OPACITY)))
        base = Image.alpha_composite(base, overlay)
    out = io.BytesIO()
    base.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def prune_cache():
    files = []
    for root, _, names in os.walk(CACHE_DIR):
        for n in names:
            p = os.path.join(root, n)
            try:
                st = os.stat(p)
                files.append((st.st_mtime, st.st_size, p))
            except OSError:
                pass
    total = sum(f[1] for f in files)
    for _, size, p in sorted(files):
        if total <= CACHE_MAX_BYTES * 0.9:
            break
        try:
            os.remove(p)
            total -= size
        except OSError:
            pass


def get_tile(layer, z, x, y):
    global _writes
    path = os.path.join(CACHE_DIR, layer, str(z), str(x), f"{y}.jpg")
    try:
        if time.time() - os.path.getmtime(path) < CACHE_DAYS * 86400:
            with open(path, "rb") as f:
                return f.read()
    except OSError:
        pass
    data = render(layer, z, x, y)
    if data:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{threading.get_ident()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        with _lock:
            _writes += 1
            if _writes % 500 == 0:
                threading.Thread(target=prune_cache, daemon=True).start()
    return data


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        m = PATH_RE.match(self.path.split("?")[0])
        if not m or m.group(1) not in LAYERS:
            return self.send_error(404)
        layer, z, x, y = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if z > LAYERS[layer][1] or x >= 2 ** z or y >= 2 ** z:
            return self.send_error(404)
        try:
            data = get_tile(layer, z, x, y)
        except Exception as e:
            self.log_error("upstream error for %s: %s", self.path, e)
            return self.send_error(502)
        if not data:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        if "error" in fmt or (args and str(args[1:2]) not in ("('200',)",)):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Public-land tiles on http://127.0.0.1:{PORT}/tiles/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

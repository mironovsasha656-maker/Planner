#!/usr/bin/env python3
"""Assemble src/* into docs/index.html (single-file PWA). Icons, manifest and sw.js live in docs/.
Bump CACHE in docs/sw.js when shipping changes so clients drop the old cache."""
import re, struct, zlib
from pathlib import Path

root = Path(__file__).parent
src, out = root / "src", root / "docs" / "index.html"
read = lambda n: (src / n).read_text(encoding="utf-8")

html = (
    read("head.html")
    + "<style>\n" + read("style.css")
    + "</style>\n</head>\n<body>\n" + read("body.html")
    + "<script>\n" + read("parser.js") + read("app.js")
    + "</script>\n</body>\n</html>\n"
)
out.write_text(html, encoding="utf-8")
print(f"wrote {out} ({len(html)} bytes)")


# ---- icons (pure Python PNG): three terracotta bars on cream ----
def png(size, pad):
    bg, fg = (245, 244, 237), (204, 104, 70)
    rows = []
    bars = [(0.0, 0.45), (0.36, 0.72), (0.72, 1.0)]  # (x0, height) inside the drawing area
    a0, a1 = pad, size - pad
    span = a1 - a0
    bw = span * 0.24
    xs = [a0 + span * 0.08 + i * span * 0.34 for i in range(3)]
    hs = [0.42, 0.68, 0.95]
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            c = bg
            for bx, h in zip(xs, hs):
                top = a1 - span * h * 0.9
                if bx <= x < bx + bw and top <= y < a1 - span * 0.05:
                    c = fg
            row += bytes(c)
        rows.append(bytes(row))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")

for name, size, pad in [("icon-192.png", 192, 26), ("icon-512.png", 512, 70), ("icon-maskable-512.png", 512, 130)]:
    (root / "docs" / name).write_bytes(png(size, pad))

# ---- manifest colors / service-worker version ----
mf = root / "docs" / "manifest.webmanifest"
mf.write_text(mf.read_text(encoding="utf-8").replace("#090e18", "#1c1b19").replace("#1f3864", "#f5f4ed"), encoding="utf-8")
sw = root / "docs" / "sw.js"
sw.write_text(re.sub(r"planner-[\d.]+", "planner-1.3.0", sw.read_text(encoding="utf-8"), count=1), encoding="utf-8")
print("icons, manifest, sw updated")

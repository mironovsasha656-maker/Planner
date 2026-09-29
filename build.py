#!/usr/bin/env python3
"""Assemble src/* into docs/index.html (single-file PWA). Icons, manifest and sw.js live in docs/.
Bump CACHE in docs/sw.js when shipping changes so clients drop the old cache."""
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

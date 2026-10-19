"""Generate AppIcon.ico for the Windows build — pure stdlib.

Reuses the same renderer as make_icon.py so both platforms ship identical art.
The ICO container holds PNG-compressed entries, which every Windows version
since Vista accepts and which keeps the file small without a BMP encoder.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_icon import render  # noqa: E402

# Explorer/taskbar use 16/32/48; 256 covers high-DPI and large icon views.
SIZES = (16, 32, 48, 256)


def build_ico() -> bytes:
    images = [(size, render(size)) for size in SIZES]

    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))  # reserved, type, count
    offset = 6 + 16 * len(images)
    for size, png in images:
        # Width/height are single bytes; 256 is encoded as 0.
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    for _, png in images:
        out += png
    return bytes(out)


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "AppIcon.ico")
    with open(path, "wb") as f:
        f.write(build_ico())
    print("built", path, f"({os.path.getsize(path):,} bytes)")


if __name__ == "__main__":
    main()

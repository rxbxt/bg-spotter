"""Generate AppIcon.icns — pure stdlib (zlib/struct), supersampled AA.

Design: near-black rounded square; two rows of red "clip" rectangles offset
like alternating A/B tracks with overlaps; a thin bright-red playhead line.
Output: assets/AppIcon.iconset + assets/AppIcon.icns (via iconutil).
"""
import os
import struct
import subprocess
import zlib

RED = (224, 58, 58)
RED_BRIGHT = (240, 75, 75)
BG_TOP = (20, 23, 24)
BG_BOT = (9, 11, 12)


def render(size: int) -> bytes:
    """Render RGBA rows for a `size`×`size` icon (top row first)."""
    ss = 4                      # supersample factor
    n = size * ss
    radius = 0.225 * n          # macOS-style squircle-ish corner

    # clip bars in normalized coords: (x0, x1) per bar, two rows
    row_a = [(0.13, 0.47), (0.55, 0.87)]           # track A clips
    row_b = [(0.20, 0.60), (0.68, 0.92)]           # track B, overlaps A
    playhead = 0.50

    rows_out = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            r_acc = g_acc = b_acc = a_acc = 0.0
            for sy in range(ss):
                py = (y * ss + sy + 0.5) / n
                px_base = x * ss
                for sx in range(ss):
                    px = (px_base + sx + 0.5) / n
                    # rounded-rect mask
                    inside = True
                    if px < radius_frac or px > 1 - radius_frac or py < radius_frac or py > 1 - radius_frac:
                        cx = min(max(px, radius_frac), 1 - radius_frac)
                        cy = min(max(py, radius_frac), 1 - radius_frac)
                        dx, dy = px - cx, py - cy
                        inside = (dx * dx + dy * dy) <= (radius / n) ** 2
                    if not inside:
                        continue  # transparent
                    # vertical gradient background
                    t = py
                    r, g, b = (BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t for i in range(3))
                    # clip bars
                    def bar(row_bars, y0, y1):
                        for bx0, bx1 in row_bars:
                            if bx0 <= px <= bx1 and y0 <= py <= y1:
                                return True
                        return False
                    if bar(row_a, 0.30, 0.46) or bar(row_b, 0.54, 0.70):
                        r, g, b = RED
                    # playhead
                    if abs(px - playhead) < 0.012 and 0.20 <= py <= 0.80:
                        r, g, b = RED_BRIGHT
                    r_acc += r; g_acc += g; b_acc += b; a_acc += 1.0
            if a_acc == 0:
                row += bytes(4)
            else:
                row += bytes((int(r_acc / (ss * ss)), int(g_acc / (ss * ss)),
                              int(b_acc / (ss * ss)), int(255 * a_acc / (ss * ss))))
        rows_out.append(bytes(row))

    raw = b"".join(b"\x00" + r for r in rows_out)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    return png


# normalized corner radius constant used in the mask test above
radius_frac = 0.225


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    iconset = os.path.join(base, "AppIcon.iconset")
    os.makedirs(iconset, exist_ok=True)
    specs = [
        ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
    ]
    for name, size in specs:
        with open(os.path.join(iconset, name), "wb") as f:
            f.write(render(size))
    subprocess.run(["iconutil", "-c", "icns", iconset,
                    "-o", os.path.join(base, "AppIcon.icns")], check=True)
    print("built", os.path.join(base, "AppIcon.icns"))


if __name__ == "__main__":
    main()

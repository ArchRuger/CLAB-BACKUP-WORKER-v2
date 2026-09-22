#!/usr/bin/env python3
"""Compose the guide's screenshots from raw captures plus numbered callouts.

Reads screenshots/spec.json (a JSON list) and, for each entry, crops an
optional region out of a raw screenshot, optionally rescales it, draws
numbered callout badges, and writes the result to screenshots/<out>.

spec.json format -- a JSON list of objects:

    {
      "out": "a02-topology-file.png",
      "src": "raw/a02-topology-file.png",
      "crop": [x, y, w, h],           // optional; raw-image pixels
      "scale": 0.5,                    // optional; default 1.0
      "callouts": [                    // optional
        {
          "n": 1,
          "x": 420, "y": 96,           // raw-image pixels (same space as "crop")
          "label": "Deploy lab",       // documentation only, not drawn
          "anchor": "top-left"         // optional: top-left (default),
                                        // top-right, bottom-left,
                                        // bottom-right, center
        }
      ],
      "badge": 30                      // optional; pins the badge diameter
                                        // in output px instead of the
                                        // automatic size below
    }

All paths ("src", "out") are relative to the screenshots/ directory itself.
"crop" and callout "x"/"y" share one coordinate space: raw pixels of the
source PNG named by "src" (the raw captures are taken at
device_scale_factor 2, so this is already twice the CSS pixel size — give
crop and callout coordinates in the file's own pixel grid, not CSS pixels).
The callout badge is drawn after cropping and scaling, sized as a fraction
of the composed image's own (output) width — about 26-40px, clamped at
both ends — rather than a fixed raw-pixel size: the guide always shrinks a
wide screenshot down to its ~6.9in text column, so a fixed-raw-pixel badge
on a wide crop becomes a near-invisible dot once printed. Set "badge" on an
entry to override the automatic size for that one figure.

"label" is carried through only for --list and for the guide author's own
reference (e.g. cross-checking a figure caption); this tool never draws the
label text on the image, only the numbered circle described above.

Determinism: composing the same spec + raw image twice produces pixel
identical output (same PIL/Pillow version, no random state, no embedded
timestamps). PNG encoding can differ in byte layout only across different
zlib/libpng builds; this tool never varies its own encoder settings, so runs
on the same machine are byte identical too.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SCREENSHOTS_DIR = HERE.parent / "screenshots"

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
# The badge is sized relative to the OUTPUT image (after crop + scale), not
# fixed in raw pixels: the guide always shrinks a wide screenshot down to
# the ~6.9in text column, so a badge that is a fixed raw-pixel size becomes
# a near-invisible dot on a wide crop (a 34px badge on a 2732px-wide image
# prints at well under 2mm). Sizing it as a fraction of the composed
# image's own width keeps it at roughly the same *printed* size (about
# 2.5-3mm, ~26-30px in a typical <=1600px-wide output) regardless of how
# wide the source crop was. `BADGE_MIN`/`BADGE_MAX` keep it sane at the
# extremes (a small already-tight crop, or a deliberately huge overview).
BADGE_DIAMETER_RATIO = 0.018
BADGE_MIN = 26
BADGE_MAX = 40
BADGE_FILL = (192, 90, 28, 255)      # matches the .step .n accent colour (#c05a1c)
BADGE_OUTLINE = (255, 255, 255, 255)
BADGE_OUTLINE_WIDTH = 2
BADGE_TEXT_FILL = (255, 255, 255, 255)
BADGE_MARGIN_RATIO = 0.15            # gap between the anchor point and the badge edge

ANCHOR_DIRECTIONS = {
    "top-left": (-1, -1),
    "top-right": (1, -1),
    "bottom-left": (-1, 1),
    "bottom-right": (1, 1),
    "center": (0, 0),
}


class SpecError(Exception):
    """Raised for a problem in one spec.json entry; the message names it."""


def load_spec(spec_path):
    if not spec_path.exists():
        raise SpecError(f"spec file not found: {spec_path}")
    with spec_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise SpecError(f"{spec_path} must contain a JSON list of entries")
    return data


def entry_label(entry, index):
    return entry.get("out") or f"entry #{index}"


def compose_entry(entry, screenshots_dir, index):
    from PIL import Image, ImageDraw, ImageFont

    label = entry_label(entry, index)
    if "out" not in entry:
        raise SpecError(f"{label}: missing required 'out'")
    if "src" not in entry:
        raise SpecError(f"{label}: missing required 'src'")

    src_path = screenshots_dir / entry["src"]
    if not src_path.exists():
        raise SpecError(f"{label}: source raw file not found: {entry['src']}")

    with Image.open(src_path) as im:
        image = im.convert("RGBA")

    crop_x, crop_y = 0, 0
    crop = entry.get("crop")
    if crop is not None:
        if len(crop) != 4:
            raise SpecError(f"{label}: 'crop' must be [x, y, w, h]")
        crop_x, crop_y, crop_w, crop_h = crop
        box = (crop_x, crop_y, crop_x + crop_w, crop_y + crop_h)
        if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
            raise SpecError(
                f"{label}: crop {list(crop)} is outside the source image "
                f"({image.width}x{image.height})"
            )
        image = image.crop(box)

    scale = entry.get("scale", 1.0)
    if scale != 1.0:
        new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(new_size, Image.LANCZOS)

    callouts = entry.get("callouts", [])
    if callouts:
        # One badge size per composed image: computed from the OUTPUT
        # width (post crop+scale) unless the entry pins an exact diameter
        # with "badge" (raw output px) for a figure that needs hand tuning.
        badge_diameter = entry.get("badge")
        if badge_diameter is None:
            badge_diameter = max(
                BADGE_MIN, min(BADGE_MAX, round(image.width * BADGE_DIAMETER_RATIO))
            )
        draw = ImageDraw.Draw(image)
        font_size = max(10, int(badge_diameter * 0.55))
        font = ImageFont.truetype(FONT_PATH, font_size)
        radius = badge_diameter / 2
        margin = max(3, round(badge_diameter * BADGE_MARGIN_RATIO))

    for callout in callouts:
        if "n" not in callout or "x" not in callout or "y" not in callout:
            raise SpecError(f"{label}: each callout needs 'n', 'x' and 'y'")
        anchor = callout.get("anchor", "top-left")
        if anchor not in ANCHOR_DIRECTIONS:
            raise SpecError(
                f"{label}: callout {callout['n']} has unknown anchor '{anchor}'"
            )
        dx, dy = ANCHOR_DIRECTIONS[anchor]

        raw_x, raw_y = callout["x"], callout["y"]
        final_x = (raw_x - crop_x) * scale
        final_y = (raw_y - crop_y) * scale

        offset = radius + margin
        center_x = final_x + dx * offset
        center_y = final_y + dy * offset

        bbox = (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        )
        draw.ellipse(
            bbox,
            fill=BADGE_FILL,
            outline=BADGE_OUTLINE,
            width=BADGE_OUTLINE_WIDTH,
        )

        text = str(callout["n"])
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        text_xy = (
            center_x - text_w / 2 - text_bbox[0],
            center_y - text_h / 2 - text_bbox[1],
        )
        draw.text(text_xy, text, font=font, fill=BADGE_TEXT_FILL)

    out_path = screenshots_dir / entry["out"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format="PNG")
    return out_path


def cmd_list(spec, screenshots_dir):
    for index, entry in enumerate(spec, start=1):
        out = entry.get("out", "<missing out>")
        src = entry.get("src", "<missing src>")
        src_path = screenshots_dir / src if "src" in entry else None
        exists = src_path.exists() if src_path else False
        n_callouts = len(entry.get("callouts", []))
        print(f"{index:3d}  out={out!r:40s} src={src!r:35s} exists={exists!s:5s} callouts={n_callouts}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--screenshots-dir",
        type=Path,
        default=DEFAULT_SCREENSHOTS_DIR,
        help="directory holding spec.json, raw/ and the composed output (default: ../screenshots)",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="path to spec.json (default: <screenshots-dir>/spec.json)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the entries and whether their sources exist; do not compose",
    )
    args = parser.parse_args(argv)

    screenshots_dir = args.screenshots_dir
    spec_path = args.spec or (screenshots_dir / "spec.json")

    if not spec_path.exists():
        # Not yet authored (the guide writer owns spec.json) is not a broken
        # pipeline: nothing to compose yet.
        print(f"no spec.json at {spec_path}; nothing to compose")
        return 0

    try:
        spec = load_spec(spec_path)
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.list:
        cmd_list(spec, screenshots_dir)
        return 0

    if not spec:
        print("no entries in spec.json; nothing to compose")
        return 0

    errors = []
    written = []
    for index, entry in enumerate(spec, start=1):
        try:
            out_path = compose_entry(entry, screenshots_dir, index)
            written.append(out_path)
        except SpecError as exc:
            errors.append(str(exc))

    for path in written:
        print(f"wrote {path}")

    if errors:
        for err in errors:
            print(f"error: {err}", file=sys.stderr)
        return 1

    print(f"composed {len(written)} screenshot(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

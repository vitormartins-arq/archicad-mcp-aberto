"""Set each camera of a shot list, grab the 3D window and build a contact sheet.

    python shoot.py <shots.json> <out_dir> [sheet_name]

Shot list entries (lengths in meters, view cone in degrees for readability):

    {"id": "living_1P01", "cam": [x, y, z], "tgt": [x, y], "cone": 60, "two": false}

The target takes the camera height unless a third value is given, so the camera stays
level. Always pass "two": the add-on keeps the previous two-point setting otherwise.
A top view for orientation:
{"id": "top", "cam": [cx, cy, 90], "tgt": [cx, cy + 0.5, 0], "cone": 63}.
"""

import base64
import json
import math
import os
import sys

from acapi import addon_result
from PIL import Image, ImageDraw, ImageFont


def perspective(shot):
    cx, cy, cz = shot["cam"]
    tz = shot["tgt"][2] if len(shot["tgt"]) > 2 else cz
    p = {
        "camera": {"x": cx, "y": cy, "z": cz},
        "target": {"x": shot["tgt"][0], "y": shot["tgt"][1], "z": tz},
        "viewCone": math.radians(shot.get("cone", 60)),
        "twoPointPerspective": shot.get("two", False),
    }
    return {"perspective": p}


def snapshot():
    """The 3D camera and cut as found, to put back at the end."""
    return addon_result("Get3DCamera"), addon_result("Get3DCutPlanes")


def restore(state):
    camera, cut = state
    if camera.get("isPerspective"):
        keys = ("camera", "target", "viewCone", "twoPointPerspective")
        addon_result("Set3DCamera", {"perspective": {k: camera[k] for k in keys}})
    else:
        keys = ("azimuth", "projectionMode")
        addon_result("Set3DCamera", {"parallel": {k: camera[k] for k in keys if k in camera}})
    addon_result("Set3DCutPlanes", {k: cut[k] for k in ("enabled", "planes") if k in cut})


def grab(path):
    resp = addon_result("Get3DWindowImage", {"format": "png"})
    with open(path, "wb") as f:
        f.write(base64.b64decode(resp["image"]))


def contact_sheet(items, path, cols=3, w=700, h=400):
    rows = math.ceil(len(items) / cols)
    sheet = Image.new("RGB", (cols * w, rows * (h + 30)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        font = None
    for i, (label, img_path) in enumerate(items):
        im = Image.open(img_path).convert("RGB")
        im.thumbnail((w, h))
        x, y = (i % cols) * w, (i // cols) * (h + 30)
        sheet.paste(im, (x, y + 30))
        draw.text((x + 6, y + 4), label, fill="black", font=font)
    sheet.save(path, quality=80)


def main(shots_path, out_dir, sheet_name="sheet"):
    os.makedirs(out_dir, exist_ok=True)
    with open(shots_path, encoding="utf-8") as f:
        shots = json.load(f)
    state = snapshot()
    addon_result("Set3DCutPlanes", {"enabled": False})
    done = []
    for shot in shots:
        try:
            addon_result("Set3DCamera", perspective(shot))
            img = os.path.join(out_dir, shot["id"] + ".png")
            grab(img)
            done.append((shot["id"], img))
            print(shot["id"], "ok")
        except RuntimeError as e:
            print(shot["id"], "FAILED", e)
    restore(state)
    if done:
        contact_sheet(done, os.path.join(out_dir, sheet_name + ".jpg"))


if __name__ == "__main__":
    main(*sys.argv[1:4])

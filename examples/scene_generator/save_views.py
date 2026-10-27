"""Save the kept shots as views in the View Map, then put the 3D window back as it was.

    python save_views.py <views.json> <root folder> [<root folder> ...]

The root is the full View Map path down to the scenes folder, starting at the top
level, e.g. "TEMPLATE" "02 | 3D MODEL" "ROOMS" when the scenes folder sits inside a
template folder. Each entry adds its own room folder:

    {"folder": "04 GYM", "name": "GYM - 1P 01",
     "cam": [x, y, z], "tgt": [x, y], "cone": 65, "two": false}
    {"folder": "AXONOMETRICS", "name": "AXONOMETRIC GENERAL",
     "parallel": {"azimuth": 1.676, "projectionMode": 15}, "cut": null}
    {"folder": "AXONOMETRICS", "name": "AXONOMETRIC GROUND FLOOR",
     "parallel": {...}, "cut": 1.5}

"cut" is the height in meters of a horizontal 3D cutting plane (null for none). Test one
view before saving them all: save it, move the camera away, open the view and check it
shows the saved camera.
"""

import json
import sys

from acapi import addon_result
from shoot import perspective, restore, snapshot


def cut_planes(height, pen):
    if height is None:
        return {"enabled": False}
    # Horizontal plane z = height; cutStatus 8 removes what is above it (live, AC30 3001).
    plane = {"cutStatus": 8, "cutPen": pen, "pa": 0, "pb": 0, "pc": 1, "pd": height}
    return {"enabled": True, "planes": [plane]}


def main(views_path, root):
    with open(views_path, encoding="utf-8") as f:
        views = json.load(f)
    state = snapshot()
    cut = state[1]
    pen = cut["planes"][0].get("cutPen", 1) if cut.get("planes") else 1
    try:
        for v in views:
            if "parallel" in v:
                addon_result("Set3DCamera", {"parallel": v["parallel"]})
                addon_result("Set3DCutPlanes", cut_planes(v.get("cut"), pen))
                addon_result("Show3DAll", {"fitInWindow": True})
            else:
                addon_result("Set3DCutPlanes", {"enabled": False})
                addon_result("Set3DCamera", perspective(v))
            r = addon_result("Save3DView", {"name": v["name"], "folderPath": root + [v["folder"]]})
            print(v["name"], "->", r["viewGuid"])
    finally:
        restore(state)
        print("3D window restored")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])

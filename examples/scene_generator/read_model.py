"""Read zones and element boxes, and draw a quick plan to plan the cameras on.

    python read_model.py <out_dir>

Writes <out_dir>/zones.json, <out_dir>/elements.json and <out_dir>/plan.png. Uses only the
official JSON API (no Tapir): zone name, number and area, and the 3D bounding box of
every zone, wall, column, object, door, window and curtain wall. Boxes are enough to
place cameras in rectangular rooms; check odd shapes with a top view (see shoot.py).
"""

import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from acapi import call  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

COLORS = {
    "Wall": "k",
    "Column": "b",
    "Object": "orange",
    "Door": "g",
    "Window": "c",
    "CurtainWall": "m",
}


def boxes(elements):
    if not elements:
        return []
    bbs = call("API.Get3DBoundingBoxes", {"elements": elements})["result"]["boundingBoxes3D"]
    return [b.get("boundingBox3D") for b in bbs]


def read_zones():
    zones = call("API.GetElementsByType", {"elementType": "Zone"})["result"]["elements"]
    names = ["Zone_ZoneName", "Zone_ZoneNumber", "Zone_CalculatedArea"]
    ids = call(
        "API.GetPropertyIds",
        {"properties": [{"type": "BuiltIn", "nonLocalizedName": n} for n in names]},
    )["result"]["properties"]
    vals = call("API.GetPropertyValuesOfElements", {"elements": zones, "properties": ids})[
        "result"
    ]["propertyValuesForElements"]
    out = []
    for z, v, b in zip(zones, vals, boxes(zones), strict=True):
        row = {"guid": z["elementId"]["guid"], "bb": b}
        for n, pv in zip(names, v["propertyValues"], strict=True):
            row[n] = pv.get("propertyValue", {}).get("value")
        out.append(row)
    return out


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    zones = read_zones()
    elements = {}
    for t in COLORS:
        els = call("API.GetElementsByType", {"elementType": t})["result"]["elements"]
        elements[t] = [b for b in boxes(els) if b]
    with open(os.path.join(out_dir, "zones.json"), "w", encoding="utf-8") as f:
        json.dump(zones, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "elements.json"), "w") as f:
        json.dump(elements, f, indent=0)

    floor = [z for z in zones if z["bb"] and z["bb"]["zMin"] < 1]
    xs = [z["bb"][k] for z in floor for k in ("xMin", "xMax")]
    ys = [z["bb"][k] for z in floor for k in ("yMin", "yMax")]
    fig, ax = plt.subplots(figsize=(26, 22))
    for z in floor:
        b = z["bb"]
        ax.add_patch(
            Rectangle(
                (b["xMin"], b["yMin"]),
                b["xMax"] - b["xMin"],
                b["yMax"] - b["yMin"],
                fill=False,
                ec="r",
                ls="--",
            )
        )
        label = f"{z['Zone_ZoneNumber']} {z['Zone_ZoneName']}"
        ax.text(
            (b["xMin"] + b["xMax"]) / 2,
            (b["yMin"] + b["yMax"]) / 2,
            label,
            color="r",
            fontsize=10,
            ha="center",
        )
    for t, c in COLORS.items():
        for b in elements[t]:
            if b["zMin"] > 3 or b["zMax"] < 0.05:  # ground floor only
                continue
            w, h = b["xMax"] - b["xMin"], b["yMax"] - b["yMin"]
            if w * h > 40 and min(w, h) > 1:  # diagonal walls, big slabs or glass boxes: skip
                continue
            ax.add_patch(
                Rectangle(
                    (b["xMin"], b["yMin"]),
                    max(w, 0.05),
                    max(h, 0.05),
                    fc=c,
                    ec=c,
                    alpha=0.5 if t == "Object" else 0.9,
                )
            )
    ax.set_xlim(min(xs) - 2, max(xs) + 2)
    ax.set_ylim(min(ys) - 2, max(ys) + 2)
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    plt.savefig(os.path.join(out_dir, "plan.png"), dpi=60, bbox_inches="tight")
    for z in sorted(floor, key=lambda z: str(z["Zone_ZoneNumber"])):
        b = z["bb"]
        print(
            f"{z['Zone_ZoneNumber']} {z['Zone_ZoneName']}: {z['Zone_CalculatedArea']:.1f} m2, "
            f"x {b['xMin']:.2f}..{b['xMax']:.2f}, y {b['yMin']:.2f}..{b['yMax']:.2f}"
        )


if __name__ == "__main__":
    main(sys.argv[1])

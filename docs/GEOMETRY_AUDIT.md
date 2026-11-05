# Geometry triage without changing the model

`audit_geometry` checks 1–500 **explicit element GUIDs** with the existing official
`Get3DBoundingBoxes` batch. It does not need Tapir or the companion add-on. It does
not enumerate the whole model, change selection, open a view, repair or save anything.

This is a small, independent implementation of a useful model-quality workflow. The
[official MCP tool catalog](https://help.graphisoft.com/AC/30/INT/Topics/001_GettingHelp/AI_Assistant/SupportedMCPTools.html)
describes broader model-health checks, but reserves that server for Collaborate/Max.
Our implementation uses the JSON API already used by `get_bounding_boxes`; it does
not connect to, copy implementation from or unlock the licensed official MCP server.

## Inputs and findings

Lengths are in metres relative to the **project/global origin**, not the survey point.

| Input | Default | Meaning |
|---|---|---|
| `element_guids` | Required | 1–500 GUIDs; canonicalized and deduplicated in input order |
| `port` | Resolve unambiguous instance | Never chooses the first of multiple instances |
| `max_origin_distance_m` | 10000 | Flag when the nearest point of the 3D box is farther away |
| `max_extent_m` | 500 | Flag when any axis-aligned box dimension exceeds this |
| `offset`, `limit` | 0, 20 | Page **findings**, not the input elements; maximum page 500 |

Finding codes:

- `far_from_origin`: nearest point exceeds the distance threshold. A box spanning
  the origin is not distant just because its centre is distant.
- `large_extent`: at least one dimension exceeds the extent threshold.
- `zero_size_bounds`: all three dimensions are exactly zero. Flat boxes are accepted.
- `invalid_bounds`: inverted/non-finite coordinates or overflowing dimensions returned
  by the API. Invalid coordinates are not echoed into JSON.
- `bounds_unavailable`: the API returned a per-element error; preserve it for review.

Thresholds are strict (`>`), finite and positive. Findings retain GUIDs, multiple
applicable codes and valid bounds/dimensions. Counts cover the entire requested
unique batch even when only a short page is returned. `has_more` and `next_offset`
make truncation explicit. Unflagged bounds are omitted to reduce response tokens.
Duplicate GUIDs are requested once. Apart from target discovery, one API call reads
the batch. Pagination re-reads it and is not a frozen project snapshot.

## Interpretation limits

These are **review candidates, not confirmed defects**. Georeferenced sites and large
buildings may legitimately exceed the thresholds; point-sized elements may be intentional.
The view/API may not provide a usable 3D box for every element. Missing/unreadable boxes
are not silently counted as healthy and do not diagnose missing library parts.

Bounds alone cannot count polygons, prove duplicate geometry or corrupt bodies, or
certify whole-model health. Empty findings mean only that this explicit batch did not
trigger these heuristics. Very large finite coordinates whose distance exceeds numeric
range still trigger `far_from_origin`; the unrepresentable distance is returned as null.

## Manual validation

Call the tool for a few known 3D elements in the identified project; compare dimensions
with `get_bounding_boxes(mode="3d")`. Adjust thresholds to produce a small set of
candidates and check the reported GUIDs, counts and pagination. Verify selection and
model remain unchanged. Try an unavailable/plan-only element and inspect its error.

Unit tests use the existing documented JSON fixture and MockTransport, not live
captures. A live test of this new tool remains pending. No APX or native code changed.

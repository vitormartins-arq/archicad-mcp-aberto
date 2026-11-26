# Slab dimension safety and radial candidate

Requires private companion R34. R33 and earlier may create static linear dimensions
from Slab hotspots. Do not use that path on real models until updated and tested.
The Python preview now refuses Slab points without a resolved persistent nodeId.
Read-back also rejects static=true and node ID changes. Duplicate signatures use
persistent Slab vertex IDs, not just mutable hotspot ordinals. The native batch
must roll back all new elements on a creation/association failure.

get_radial_dimensions reads native references/radius/style; create_radial_dimensions
is a development candidate using favorite, floor_index, slab_guid, arc_begin_index
and end_point. The native planner derives the actual arc radius and edge identity;
there is no static fallback. Shared preview/token/receipts, native re-plan, one Undo
and independent read-back apply. All lengths are metres. Favorite/project precision
is native; this does not fabricate formatted text.

Slab arc association has NOT been validated live. Passing compilation or offline
mocks does not establish that the SDK accepts/preserves the reference. Test one
dimension in a disposable project, rebuild and change its parent arc/vertex, verify
the value and association, repeat without duplicates, Undo once and reopen. Only
after this acceptance should the project chat apply dimensions on the WG.

This implementation does not edit the WG/Template, replace installed APXs or
restart a session. Installing the matching native module and reconnecting the MCP
are distinct steps; a previously running tool catalog remains unchanged.

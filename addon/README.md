# Native add-on

Tapir is the main engine inside Archicad. Commands Tapir lacks go here, so the MCP does
not wait for a Tapir release (Vitor, 21/10/2026). Each one is also offered to Tapir
upstream; when Tapir ships it, the MCP moves to Tapir's and ours is retired.

If an add-on is built:
- Each Archicad major version needs its own build with the matching API DevKit
  (Windows: Visual Studio toolset v143, x64 for Archicad 29).
- The DevKit is downloaded from Graphisoft and never committed (`addon/devkit/` is ignored).
- The MDID (Developer ID and Local ID) must be issued by Graphisoft for this add-on.
  Example IDs or IDs borrowed from another add-on make Archicad reject it.

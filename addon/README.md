# Native add-on

Empty on purpose. Tapir is the engine inside Archicad. Code goes here only for a gap
Tapir cannot cover and its maintainers do not want upstream, with an issue that shows it.

If an add-on is built:
- Each Archicad major version needs its own build with the matching API DevKit
  (Windows: Visual Studio toolset v143, x64 for Archicad 29).
- The DevKit is downloaded from Graphisoft and never committed (`addon/devkit/` is ignored).
- The MDID (Developer ID and Local ID) must be issued by Graphisoft for this add-on.
  Example IDs or IDs borrowed from another add-on make Archicad reject it.

# Security

The server only connects to Archicad on `localhost` and makes no other network calls.
Archicad's JSON API has no authentication: any local program can call it. Do not expose
the Archicad ports to a network.

Future script tools will run Python as your user, outside Archicad, without a sandbox.
They will dry-run by default; review a plan before applying it.

Report vulnerabilities privately through GitHub's "Report a vulnerability" button on
this repository, not in a public issue.

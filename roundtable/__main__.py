"""`python -m roundtable` entry point.

Forwards to mcp_server.main(); the .mcpb bundle's manifest invokes
this module. Keeping `__main__.py` as a one-liner lets tests import
`roundtable.mcp_server` directly without triggering server startup.
"""

from __future__ import annotations

from .mcp_server import main

main()

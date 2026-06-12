"""Entry point for the Stock MCP Service.

This module constructs the FastMCP server instance used to expose stock
market tools and prefab UI dashboards. Tools and apps are registered
elsewhere (see `tools/` and `ui/`) and mounted onto this server.
"""

from fastmcp import FastMCP

mcp: FastMCP = FastMCP("StockMCP")


if __name__ == "__main__":
    mcp.run()

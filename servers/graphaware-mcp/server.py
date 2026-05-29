"""GraphAware Hume MCP server for DataExpert agentic AI.

Entry point for the dataexpert-graphaware-mcp package.
All underlying logic lives in core_engine.adapters.graphaware.client.
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from core_engine.adapters.graphaware.client import hume_request, run_compose

mcp = FastMCP("graphaware-adapter")


# ---------------------------------------------------------------------------
# Stack management
# ---------------------------------------------------------------------------

@mcp.tool()
async def hume_stack_status() -> dict[str, Any]:
    """List all containers and their state in the hume-300 compose stack."""
    return run_compose("ps")


@mcp.tool()
async def hume_stack_start(detach: bool = True) -> dict[str, Any]:
    """Start the hume-300 compose stack.

    detach: run in background (default True). Set False to follow logs (blocking).
    """
    args = ["up", "--detach"] if detach else ["up"]
    return run_compose(*args)


@mcp.tool()
async def hume_stack_stop(remove_volumes: bool = False) -> dict[str, Any]:
    """Stop and remove hume-300 containers.

    remove_volumes: also delete Postgres data volumes (default False — data is preserved).
    """
    args = ["down"] + (["-v"] if remove_volumes else [])
    return run_compose(*args)


@mcp.tool()
async def hume_stack_restart(service: str = "") -> dict[str, Any]:
    """Restart one service or the whole hume-300 stack.

    service: container name suffix — 'api', 'web', 'orchestra', 'eventstore', 'media',
             or a postgres sidecar. Leave empty to restart everything.
    """
    args = ["restart"] + ([service] if service else [])
    return run_compose(*args)


@mcp.tool()
async def hume_stack_logs(service: str = "", lines: int = 100) -> dict[str, Any]:
    """Tail logs from the hume-300 stack.

    service: filter to one container (e.g. 'api', 'web'). Empty = all services.
    lines:   number of tail lines (default 100).
    """
    args = ["logs", "--no-color", f"--tail={lines}"] + ([service] if service else [])
    return run_compose(*args)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@mcp.tool()
async def hume_health() -> dict[str, Any]:
    """Check the Hume API Spring Boot actuator health endpoint (/actuator/health).

    Returns {"status_code": int, "body": {...}} or {"error": "..."} if unreachable.
    """
    try:
        status_code, body = hume_request("GET", "/actuator/health")
        return {"status_code": status_code, "body": body}
    except Exception as exc:
        return {"error": str(exc), "status_code": None, "body": None}


# ---------------------------------------------------------------------------
# Generic API passthrough
# ---------------------------------------------------------------------------

@mcp.tool()
async def hume_api_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic passthrough to any Hume REST API endpoint with automatic JWT auth.

    Covers the full Hume API surface including:
      Resources    /api/v1/ecosystem/resources
      KGs          /api/v1/knowledgeGraphs
      Perspectives /api/v1/knowledgeGraphs/{id}/perspectives
      Schema       /api/v1/knowledgeGraphs/{id}/schema/classes|relationships
      Workspaces   /api/v1/workspaces
      Datasources  /api/v1/datasources
      Search       /api/v1/search
      ...and any other endpoint in the OpenAPI spec.

    method: HTTP verb — GET, POST, PUT, PATCH, DELETE
    path:   Full path starting with /, e.g. /api/v1/knowledgeGraphs
    body:   Optional JSON body (for POST/PUT/PATCH)

    Returns {"status_code": int, "body": <response JSON or null>}.
    The JWT is obtained automatically and refreshed on 401.
    """
    try:
        status_code, response_body = hume_request(method, path, body)
        return {"status_code": status_code, "body": response_body}
    except Exception as exc:
        return {"error": str(exc), "method": method, "path": path}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

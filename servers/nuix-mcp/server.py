"""Nuix Automate MCP server for DataExpert agentic AI.

Entry point for the dataexpert-nuix-mcp package.
Query-builder helpers live in core_engine.adapters.nuix.query_builder.
OpenAPI describe helpers live in core_engine.adapters.nuix.openapi_describe.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from core_engine.adapters.nuix.adapter import NuixAutomateClient
from core_engine.adapters.nuix.openapi import extract_operations, load_openapi
from core_engine.adapters.nuix.session_manager import NuixSessionManager
from core_engine.adapters.nuix.query_builder import (
    _build_query_from_intent,
    build_search_query as _build_search_query,
)
from core_engine.adapters.nuix.openapi_describe import (
    _resolve_api_base_url,
    _build_url,
    _build_body_example,
    _build_curl,
    suggest_openapi_endpoint as _suggest_openapi_endpoint,
    describe_openapi_call as _describe_openapi_call,
)


# Load local secrets.env so the MCP server has Automate credentials.
ROOT = Path(__file__).resolve().parents[3]
try:
    load_dotenv(ROOT / "security" / "secrets.env", override=False, interpolate=False)
except TypeError:
    load_dotenv(ROOT / "security" / "secrets.env", override=False)

# MCP server that exposes Nuix tools to the agent runtime.
mcp = FastMCP("nuix-adapter")
# Cache a single client to reuse config and HTTP settings.
_client: Optional[NuixAutomateClient] = None
# Cache a single session manager.
_session_manager: Optional[NuixSessionManager] = None


def _get_client() -> NuixAutomateClient:
    global _client
    if _client is None:
        # Lazy init so missing env vars only error on first use.
        _client = NuixAutomateClient()
    return _client


def _get_session_manager() -> NuixSessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = NuixSessionManager(_get_client())
    return _session_manager


@mcp.tool()
async def validate_nuix_connection() -> dict:
    """
    Validate connection to Nuix Automate API.

    Tests whether the API credentials are configured correctly and can connect
    to the Nuix Automate server. Call this first to ensure the agent can access
    Nuix before proceeding with other operations.

    Returns:
        dict with:
        - status: "success" or "error"
        - message: Human-readable status message
        - connected: Boolean indicating successful connection
        - base_url: Configured API base URL
        - errors: List of error messages (if any)
        - repository_count: Number of repositories available (on success)
        - repositories: Sample list of available repositories (on success)

    Example:
        result = await validate_nuix_connection()
        if result["connected"]:
            print(f"Connected to {result['base_url']}")
        else:
            print("Connection failed:", result["errors"])
    """
    client = _get_client()
    return await client.validate_connection()


@mcp.tool()
async def nuix_operation(
    operation: str,
    **kwargs: Any,
) -> dict:
    """
    Execute a Nuix Automate operation through the authenticated connection.

    This is a comprehensive wrapper tool for all Nuix Automate operations.
    Features and scripts use this single tool instead of managing connections.

    Supported operations:

    **Connection & Status:**
    - validate: Validate Nuix connection
    - list_jobs: List all non-archived jobs
    - list_repositories: List data repositories
    - list_execution_profiles: List execution profiles

    **Case Management:**
    - list_cases: List cases (params: repository_name/id, base_path, skip_folders)
    - start_case_session: Start persistent case session (params: case_path)
    - session_search: Search within session (params: session_id, query, max_items)
    - close_case_session: Close session (params: session_id)
    - list_sessions: List active sessions

    **Workflow Management:**
    - list_libraries: List workflow libraries
    - list_workflows: List workflows (params: library_id, include_disabled)
    - get_workflow: Get workflow details (params: workflow_id, library_id)
    - create_workflow: Create workflow (params: library_id, name, description, operations_xml)
    - update_workflow: Update workflow (params: workflow_id, library_id, name, description, etc.)
    - delete_workflow: Delete workflow (params: workflow_id)
    - download_workflow: Download workflow (params: workflow_id, as_base64, max_bytes)
    - import_workflow: Import workflow (params: workflow_file_base64, library_id, workflow_id, overwrite)
    - patch_workflow_defaults: Patch workflow defaults (params: workflow_id, defaults, library_id)

    **Job Execution:**
    - start_workflow: Start workflow job (params: workflow_id, session_parameters, job_name, execution_profile_id, etc.)
    - start_search: Start search workflow (params: case_path, query, max_items, output_name, execution_profile_id, etc.)
    - get_job: Get job status (params: job_id)
    - get_job_details: Get detailed job info (params: job_id)
    - get_job_file: Get job file (params: job_id, as_base64, max_bytes)
    - cancel_job: Cancel job (params: job_id, command)
    - cancel_jobs_by_pattern: Cancel jobs by pattern (params: pattern, command)

    **File Libraries:**
    - list_file_libraries: List available file libraries
    - list_file_library_files: List files in library (params: file_library_id)
    - download_file_library_file: Download file (params: file_library_id, file_id, as_base64, max_bytes)
    - upload_file_library_file: Upload file (params: file_library_id, name, data, description)
    - delete_file_library_file: Delete file (params: file_library_id, file_id)

    Args:
        operation: Name of the operation to execute
        **kwargs: Operation-specific parameters (see examples below)

    Returns:
        dict with operation result or error information

    Examples:
        # Validate and list repositories
        result = await nuix_operation("validate")
        repos = await nuix_operation("list_repositories")

        # List and execute workflows
        workflows = await nuix_operation("list_workflows", library_id="lib-123")
        job = await nuix_operation(
            "start_workflow",
            workflow_id="wf-123",
            session_parameters=[{"name": "{case_path}", "value": "/path/to/case"}]
        )

        # Manage case sessions
        session = await nuix_operation("start_case_session", case_path="/path/to/case")
        results = await nuix_operation(
            "session_search",
            session_id=session["session_id"],
            query="content:fraud"
        )
        await nuix_operation("close_case_session", session_id=session["session_id"])
    """
    client = _get_client()
    session_manager = _get_session_manager()

    try:
        # Connection & Status
        if operation == "validate":
            return await client.validate_connection()

        elif operation == "list_jobs":
            return await client.list_jobs()

        elif operation == "list_repositories":
            repositories = await client.list_repositories()
            return {
                "status": "success",
                "repositories": repositories,
                "count": len(repositories),
            }

        elif operation == "list_execution_profiles":
            return await client.list_execution_profiles()

        # Case Management
        elif operation == "list_cases":
            result = await client.list_cases(
                repository_name=kwargs.get("repository_name"),
                repository_id=kwargs.get("repository_id"),
                base_path=kwargs.get("base_path"),
                skip_folders=kwargs.get("skip_folders"),
            )
            return result

        elif operation == "start_case_session":
            case_path = kwargs.get("case_path")
            if not case_path:
                return {"status": "error", "message": "case_path is required"}
            session = await session_manager.get_or_create_session(case_path)
            return {
                "status": "success",
                "session_id": session.session_id,
                "job_id": session.job_id,
                "case_path": session.case_path,
                "created_at": session.created_at,
            }

        elif operation == "session_search":
            session_id = kwargs.get("session_id")
            if not session_id:
                return {"status": "error", "message": "session_id is required"}
            session = session_manager.get_session(session_id)
            if not session:
                return {"status": "error", "message": f"Session {session_id} not found"}
            result = await session_manager.execute_search(
                session,
                query=kwargs.get("query", "*"),
                max_items=kwargs.get("max_items", 1000),
            )
            return result

        elif operation == "close_case_session":
            session_id = kwargs.get("session_id")
            if not session_id:
                return {"status": "error", "message": "session_id is required"}
            session = session_manager.get_session(session_id)
            if session:
                await session_manager.close_session(session)
                return {"status": "success", "session_id": session_id}
            return {"status": "error", "message": f"Session {session_id} not found"}

        elif operation == "list_sessions":
            sessions = session_manager.list_sessions()
            return {
                "status": "success",
                "sessions": [
                    {
                        "session_id": s.session_id,
                        "job_id": s.job_id,
                        "case_path": s.case_path,
                        "status": s.status,
                        "created_at": s.created_at,
                        "last_activity": s.last_activity,
                        "request_count": s.request_count,
                    }
                    for s in sessions
                ],
            }

        # Workflow Management
        elif operation == "list_libraries":
            return await client.list_libraries(
                include_disabled=kwargs.get("include_disabled", False)
            )

        elif operation == "list_workflows":
            return await client.list_workflows(
                library_id=kwargs.get("library_id"),
                include_disabled=kwargs.get("include_disabled", False),
            )

        elif operation == "get_workflow":
            workflow_id = kwargs.get("workflow_id")
            if not workflow_id:
                return {"status": "error", "message": "workflow_id is required"}
            return await client.get_workflow(
                workflow_id=workflow_id,
                library_id=kwargs.get("library_id"),
                include_operations=kwargs.get("include_operations", False),
            )

        elif operation == "create_workflow":
            workflow_id = kwargs.get("workflow_id")
            if not workflow_id:
                return {"status": "error", "message": "workflow_id is required"}
            return await client.create_workflow(
                library_id=kwargs.get("library_id"),
                name=kwargs.get("name"),
                description=kwargs.get("description"),
                operations_xml=kwargs.get("operations_xml"),
                enabled=kwargs.get("enabled", True),
                payload=kwargs.get("payload"),
            )

        elif operation == "update_workflow":
            workflow_id = kwargs.get("workflow_id")
            if not workflow_id:
                return {"status": "error", "message": "workflow_id is required"}
            return await client.update_workflow(
                workflow_id=workflow_id,
                library_id=kwargs.get("library_id"),
                name=kwargs.get("name"),
                description=kwargs.get("description"),
                operations_xml=kwargs.get("operations_xml"),
                enabled=kwargs.get("enabled"),
                payload=kwargs.get("payload"),
            )

        elif operation == "delete_workflow":
            workflow_id = kwargs.get("workflow_id")
            if not workflow_id:
                return {"status": "error", "message": "workflow_id is required"}
            return await client.delete_workflow(workflow_id)

        elif operation == "download_workflow":
            workflow_id = kwargs.get("workflow_id")
            if not workflow_id:
                return {"status": "error", "message": "workflow_id is required"}
            return await client.download_workflow(
                workflow_id,
                as_base64=kwargs.get("as_base64", False),
                max_bytes=kwargs.get("max_bytes", 0),
            )

        elif operation == "import_workflow":
            workflow_file_b64 = kwargs.get("workflow_file_base64")
            if not workflow_file_b64:
                return {"status": "error", "message": "workflow_file_base64 is required"}
            return await client.import_workflow(
                workflow_file_base64=workflow_file_b64,
                library_id=kwargs.get("library_id"),
                workflow_id=kwargs.get("workflow_id"),
                file_name=kwargs.get("file_name"),
                overwrite=kwargs.get("overwrite", False),
            )

        elif operation == "patch_workflow_defaults":
            workflow_id = kwargs.get("workflow_id")
            defaults = kwargs.get("defaults")
            if not workflow_id or not defaults:
                return {
                    "status": "error",
                    "message": "workflow_id and defaults are required",
                }
            return await client.patch_workflow_defaults(
                workflow_id=workflow_id,
                defaults=defaults,
                library_id=kwargs.get("library_id"),
                overwrite=kwargs.get("overwrite", True),
            )

        # Job Execution
        elif operation == "start_workflow":
            workflow_id = kwargs.get("workflow_id")
            session_parameters = kwargs.get("session_parameters")
            if not workflow_id or not session_parameters:
                return {
                    "status": "error",
                    "message": "workflow_id and session_parameters are required",
                }
            return await client.start_workflow(
                workflow_id=workflow_id,
                session_parameters=session_parameters,
                job_name=kwargs.get("job_name"),
                submit=kwargs.get("submit", True),
                execution_profile_id=kwargs.get("execution_profile_id"),
                resource_pool_id=kwargs.get("resource_pool_id"),
                matter_id=kwargs.get("matter_id"),
                priority=kwargs.get("priority"),
            )

        elif operation == "start_search":
            case_path = kwargs.get("case_path")
            query = kwargs.get("query")
            if not case_path or not query:
                return {
                    "status": "error",
                    "message": "case_path and query are required",
                }
            return await client.start_search(
                case_path=case_path,
                query=query,
                max_items=kwargs.get("max_items", 1000),
                output_name=kwargs.get("output_name", "search_results.json"),
                job_name=kwargs.get("job_name"),
                execution_profile_id=kwargs.get("execution_profile_id"),
            )

        elif operation == "get_job":
            job_id = kwargs.get("job_id")
            if not job_id:
                return {"status": "error", "message": "job_id is required"}
            return await client.get_job(job_id)

        elif operation == "get_job_details":
            job_id = kwargs.get("job_id")
            if not job_id:
                return {"status": "error", "message": "job_id is required"}
            return await client.get_job_details(job_id)

        elif operation == "get_job_file":
            job_id = kwargs.get("job_id")
            if not job_id:
                return {"status": "error", "message": "job_id is required"}
            return await client.get_job_file(
                job_id,
                as_base64=kwargs.get("as_base64", False),
                max_bytes=kwargs.get("max_bytes", 0),
            )

        elif operation == "cancel_job":
            job_id = kwargs.get("job_id")
            if not job_id:
                return {"status": "error", "message": "job_id is required"}
            return await client.cancel_job(
                job_id,
                command=kwargs.get("command", "CANCEL"),
            )

        elif operation == "cancel_jobs_by_pattern":
            pattern = kwargs.get("pattern")
            if not pattern:
                return {"status": "error", "message": "pattern is required"}
            return await client.cancel_jobs_by_pattern(
                pattern,
                command=kwargs.get("command", "CANCEL"),
            )

        # File Libraries
        elif operation == "list_file_libraries":
            return await client.list_file_libraries()

        elif operation == "list_file_library_files":
            file_library_id = kwargs.get("file_library_id")
            if not file_library_id:
                return {"status": "error", "message": "file_library_id is required"}
            return await client.list_file_library_files(file_library_id)

        elif operation == "download_file_library_file":
            file_library_id = kwargs.get("file_library_id")
            file_id = kwargs.get("file_id")
            if not file_library_id or not file_id:
                return {
                    "status": "error",
                    "message": "file_library_id and file_id are required",
                }
            return await client.download_file_library_file(
                file_library_id,
                file_id,
                as_base64=kwargs.get("as_base64", True),
                max_bytes=kwargs.get("max_bytes", 0),
            )

        elif operation == "upload_file_library_file":
            file_library_id = kwargs.get("file_library_id")
            name = kwargs.get("name")
            data = kwargs.get("data")
            if not file_library_id or not name or not data:
                return {
                    "status": "error",
                    "message": "file_library_id, name, and data are required",
                }
            return await client.upload_file_library_file(
                file_library_id=file_library_id,
                name=name,
                data=data,
                description=kwargs.get("description", ""),
            )

        elif operation == "delete_file_library_file":
            file_library_id = kwargs.get("file_library_id")
            file_id = kwargs.get("file_id")
            if not file_library_id or not file_id:
                return {
                    "status": "error",
                    "message": "file_library_id and file_id are required",
                }
            return await client.delete_file_library_file(file_library_id, file_id)

        else:
            return {
                "status": "error",
                "message": f"Unknown operation: {operation}",
                "supported_operations": [
                    "validate", "list_jobs", "list_repositories", "list_execution_profiles",
                    "list_cases", "start_case_session", "session_search",
                    "close_case_session", "list_sessions",
                    "list_libraries", "list_workflows", "get_workflow", "create_workflow",
                    "update_workflow", "delete_workflow", "download_workflow",
                    "import_workflow", "patch_workflow_defaults",
                    "start_workflow", "start_search", "get_job", "get_job_details",
                    "get_job_file", "cancel_job", "cancel_jobs_by_pattern",
                    "list_file_libraries", "list_file_library_files",
                    "download_file_library_file", "upload_file_library_file",
                    "delete_file_library_file",
                ],
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Operation failed: {str(e)}",
            "operation": operation,
        }


@mcp.tool()
async def build_search_query(intent: dict) -> dict:
    """Build a Nuix search query from investigation intent/context."""
    return await _build_search_query(intent)


@mcp.tool()
async def list_cases(
    repository_name: Optional[str] = None,
    repository_id: Optional[str] = None,
    base_path: Optional[str] = None,
    skip_folders: Optional[Iterable[str]] = None,
    include_timings: bool = False,
    max_folders: int = 0,
    timeout_seconds: int = 0,
) -> dict:
    """List Nuix cases by locating case.fbi2 within an in-place repository."""
    client = _get_client()
    return await client.list_cases(
        repository_name=repository_name,
        repository_id=repository_id,
        base_path=base_path,
        skip_folders=skip_folders,
        include_timings=include_timings,
        max_folders=max_folders,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
async def list_libraries(
    include_disabled: bool = False,
    required_parameter_types: Optional[Iterable[str]] = None,
    forbidden_parameter_types: Optional[Iterable[str]] = None,
) -> dict:
    """List Automate workflow libraries."""
    client = _get_client()
    return await client.list_libraries(
        include_disabled=include_disabled,
        required_parameter_types=required_parameter_types,
        forbidden_parameter_types=forbidden_parameter_types,
        )


def _normalize_items(data: Any) -> list:
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
        return []
    if isinstance(data, list):
        return data
    return []


@mcp.tool()
async def list_library_names(include_disabled: bool = False) -> dict:
    """
    List all workflow libraries available in Nuix Automate.

    Returns a simplified list of workflow libraries suitable for creating workflows.
    Use this to discover available libraries before calling create_workflow().

    Args:
        include_disabled: If True, include disabled libraries. Default: False.

    Returns:
        {
            "libraries": [
                {
                    "id": "f2b17e46-713c-2219-d90c-920374af9e89",
                    "name": "Investigations",
                    "description": "Investigation workflows"
                },
                ...
            ]
        }

    Example:
        libraries = await list_library_names()
        for lib in libraries["libraries"]:
            if lib["name"] == "Investigations":
                inv_lib_id = lib["id"]
                # Use inv_lib_id with create_workflow()
    """
    client = _get_client()
    data = await client.list_libraries(include_disabled=include_disabled)
    libs = _normalize_items(data)
    result = [
        {
            "id": lib.get("id"),
            "name": lib.get("name"),
            "description": lib.get("description"),
        }
        for lib in libs
        if lib.get("id")
    ]
    return {"libraries": result}


@mcp.tool()
async def list_workflow_names(
    library_id: Optional[str] = None,
    include_disabled: bool = False,
) -> dict:
    """Return workflows (name + ID + library context) for one or all libraries."""
    client = _get_client()
    target_libraries: list[dict[str, Any]] = []
    if library_id:
        target_libraries = [{"id": library_id}]
    else:
        libs = await client.list_libraries(include_disabled=include_disabled)
        normalized = _normalize_items(libs)
        target_libraries = [
            {"id": lib.get("id"), "name": lib.get("name")}
            for lib in normalized
            if lib.get("id")
        ]
    workflows_summary: list[dict[str, Optional[str]]] = []
    for lib in target_libraries:
        lib_id = lib.get("id")
        if not lib_id:
            continue
        workflows = await client.list_workflows(library_id=lib_id)
        normalized = _normalize_items(workflows)
        for wf in normalized:
            workflows_summary.append(
                {
                    "workflow_id": wf.get("id"),
                    "workflow_name": wf.get("name") or wf.get("workflowName"),
                    "library_id": lib_id,
                    "library_name": lib.get("name"),
                }
            )
    return {"workflows": workflows_summary}


@mcp.tool()
async def list_execution_profiles(endpoints: Optional[Iterable[str]] = None) -> dict:
    """List Nuix execution profiles available to Automate."""
    client = _get_client()
    return await client.list_execution_profiles(endpoints=endpoints)


@mcp.tool()
async def list_file_libraries() -> list[dict]:
    """List available file libraries for uploads."""
    client = _get_client()
    return await client.list_file_libraries()


@mcp.tool()
async def list_file_library_files(file_library_id: str) -> list[dict]:
    """List files stored inside the specified Nuix file library."""
    client = _get_client()
    return await client.list_file_library_files(file_library_id)


@mcp.tool()
async def download_file_library_file(
    file_library_id: str,
    file_id: str,
    *,
    as_base64: bool = True,
    max_bytes: int = 0,
) -> dict:
    """Download a file from the specified Nuix file library."""
    client = _get_client()
    return await client.download_file_library_file(
        file_library_id=file_library_id,
        file_id=file_id,
        as_base64=as_base64,
        max_bytes=max_bytes,
    )


@mcp.tool()
async def list_workflows(
    library_id: Optional[str] = None,
    include_disabled: bool = False,
    required_parameter_types: Optional[Iterable[str]] = None,
    forbidden_parameter_types: Optional[Iterable[str]] = None,
) -> dict:
    """List workflows from a specific Automate library."""
    client = _get_client()
    return await client.list_workflows(
        library_id=library_id,
        include_disabled=include_disabled,
        required_parameter_types=required_parameter_types,
        forbidden_parameter_types=forbidden_parameter_types,
    )


@mcp.tool()
async def get_workflow(
    workflow_id: str,
    library_id: Optional[str] = None,
    include_operations: bool = False,
    include_detailed_operations: bool = False,
    include_required_parameters: bool = False,
) -> dict:
    """Fetch workflow details and optional operation metadata."""
    client = _get_client()
    return await client.get_workflow(
        workflow_id=workflow_id,
        library_id=library_id,
        include_operations=include_operations,
        include_detailed_operations=include_detailed_operations,
        include_required_parameters=include_required_parameters,
    )


@mcp.tool()
async def download_workflow(
    workflow_id: str,
    as_base64: bool = False,
    max_bytes: int = 0,
) -> dict:
    """Download a workflow definition (XML) from Automate."""
    client = _get_client()
    return await client.download_workflow(
        workflow_id=workflow_id,
        as_base64=as_base64,
        max_bytes=max_bytes,
    )


@mcp.tool()
async def create_workflow(
    library_id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    operations_xml: Optional[str] = None,
    operations: Optional[list] = None,
    enabled: Optional[bool] = True,
    allowed_parameter_values: Optional[dict] = None,
    icon: Optional[str] = None,
    payload: Optional[dict] = None,
) -> dict:
    """Create a new Automate workflow in the specified library."""
    client = _get_client()
    return await client.create_workflow(
        library_id=library_id,
        name=name,
        description=description,
        operations_xml=operations_xml,
        operations=operations,
        enabled=enabled,
        allowed_parameter_values=allowed_parameter_values,
        icon=icon,
        payload=payload,
    )


@mcp.tool()
async def update_workflow(
    workflow_id: str,
    library_id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    operations_xml: Optional[str] = None,
    operations: Optional[list] = None,
    enabled: Optional[bool] = None,
    allowed_parameter_values: Optional[dict] = None,
    icon: Optional[str] = None,
    payload: Optional[dict] = None,
) -> dict:
    """Update an existing Automate workflow."""
    client = _get_client()
    return await client.update_workflow(
        workflow_id=workflow_id,
        library_id=library_id,
        name=name,
        description=description,
        operations_xml=operations_xml,
        operations=operations,
        enabled=enabled,
        allowed_parameter_values=allowed_parameter_values,
        icon=icon,
        payload=payload,
    )


@mcp.tool()
async def import_workflow(
    workflow_file_base64: str,
    library_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    file_name: Optional[str] = None,
    overwrite: bool = False,
) -> dict:
    """Import or replace an Automate workflow from an exported file."""
    client = _get_client()
    return await client.import_workflow(
        workflow_file_base64=workflow_file_base64,
        library_id=library_id,
        workflow_id=workflow_id,
        file_name=file_name,
        overwrite=overwrite,
    )


@mcp.tool()
async def patch_workflow_defaults(
    workflow_id: str,
    defaults: dict[str, str],
    library_id: Optional[str] = None,
    overwrite: bool = True,
) -> dict:
    """Patch default session parameter values inside a workflow and re-import it."""
    client = _get_client()
    return await client.patch_workflow_defaults(
        workflow_id=workflow_id,
        defaults=defaults,
        library_id=library_id,
        overwrite=overwrite,
    )


@mcp.tool()
async def delete_workflow(workflow_id: str) -> dict:
    """Delete an Automate workflow by ID."""
    client = _get_client()
    return await client.delete_workflow(workflow_id=workflow_id)


@mcp.tool()
async def start_workflow(
    workflow_id: str,
    session_parameters: dict | list[dict],
    job_name: Optional[str] = None,
    submit: bool = True,
    execution_profile_id: Optional[str] = None,
    resource_pool_id: Optional[str] = None,
    matter_id: Optional[str] = None,
    priority: Optional[str] = None,
    notes: Optional[str] = None,
    in_staging: Optional[bool] = None,
) -> dict:
    """Queue an Automate workflow job with explicit session parameters."""
    client = _get_client()
    return await client.start_workflow(
        workflow_id=workflow_id,
        session_parameters=session_parameters,
        job_name=job_name,
        submit=submit,
        execution_profile_id=execution_profile_id,
        resource_pool_id=resource_pool_id,
        matter_id=matter_id,
        priority=priority,
        notes=notes,
        in_staging=in_staging,
    )


@mcp.tool()
async def start_search(
    case_path: str,
    query: str,
    max_items: int = 1000,
    output_name: str = "search_results.json",
    job_name: Optional[str] = None,
    submit: bool = True,
    execution_profile_id: Optional[str] = None,
    resource_pool_id: Optional[str] = None,
    matter_id: Optional[str] = None,
    priority: Optional[str] = None,
    notes: Optional[str] = None,
    in_staging: Optional[bool] = None,
    extra_session_parameters: Optional[list[dict]] = None,
    case_repository_id: Optional[str] = None,
    include_job_details: bool = False,
) -> dict:
    """Queue a Nuix Automate workflow that runs the search and writes to the case folder."""
    client = _get_client()
    result = await client.start_search(
        case_path=case_path,
        query=query,
        max_items=max_items,
        output_name=output_name,
        job_name=job_name,
        submit=submit,
        execution_profile_id=execution_profile_id,
        resource_pool_id=resource_pool_id,
        matter_id=matter_id,
        priority=priority,
        notes=notes,
        in_staging=in_staging,
        extra_session_parameters=extra_session_parameters,
        case_repository_id=case_repository_id,
    )
    if include_job_details:
        job_id = result.get("job_id")
        if job_id:
            try:
                result["job_details"] = await client.get_job_details(job_id)
            except Exception as exc:
                result["job_details_error"] = f"job details failed: {exc}"
    return result


@mcp.tool()
async def get_job(job_id: str) -> dict:
    """Fetch Automate job metadata by job ID."""
    client = _get_client()
    return await client.get_job(job_id)


@mcp.tool()
async def get_job_details(job_id: str) -> dict:
    """Fetch Automate job details (includes audit log and operation data)."""
    client = _get_client()
    return await client.get_job_details(job_id)


@mcp.tool()
async def get_job_file(job_id: str, as_base64: bool = False, max_bytes: int = 0) -> dict:
    """Fetch an Automate job file (execution log if available)."""
    client = _get_client()
    return await client.get_job_file(job_id, as_base64=as_base64, max_bytes=max_bytes)


@mcp.tool()
async def start_case_session(case_path: str) -> dict:
    """Start a persistent Nuix case session for faster repeated searches."""
    try:
        manager = _get_session_manager()
        session = await manager.get_or_create_session(case_path)
        return {
            "session_id": session.session_id,
            "job_id": session.job_id,
            "case_path": session.case_path,
            "status": session.status,
            "created_at": session.created_at,
        }
    except Exception as exc:
        return {"error": f"Failed to start session: {exc}"}


@mcp.tool()
async def session_search(
    session_id: str,
    query: str,
    max_items: int = 1000,
) -> dict:
    """Execute a search within an existing session (faster than start_search)."""
    try:
        manager = _get_session_manager()
        session = manager.get_session(session_id)
        if not session:
            return {"error": f"Session {session_id} not found"}

        result = await manager.execute_search(session, query, max_items)
        return result
    except Exception as exc:
        return {"error": f"Search failed: {exc}"}


@mcp.tool()
async def close_case_session(session_id: str) -> dict:
    """Close a persistent case session and release resources."""
    try:
        manager = _get_session_manager()
        session = manager.get_session(session_id)
        if session:
            await manager.close_session(session)
            return {"status": "closed", "session_id": session_id}
        return {"error": f"Session {session_id} not found"}
    except Exception as exc:
        return {"error": f"Failed to close session: {exc}"}


@mcp.tool()
async def list_sessions() -> dict:
    """List all active Nuix case sessions."""
    try:
        manager = _get_session_manager()
        sessions = manager.list_sessions()
        return {
            "sessions": [
                {
                    "session_id": s.session_id,
                    "job_id": s.job_id,
                    "case_path": s.case_path,
                    "status": s.status,
                    "created_at": s.created_at,
                    "last_activity": s.last_activity,
                    "request_count": s.request_count,
                }
                for s in sessions
            ]
        }
    except Exception as exc:
        return {"error": f"Failed to list sessions: {exc}"}


@mcp.tool()
async def list_engines() -> list:
    """List all registered Nuix engines with their current status."""
    client = _get_client()
    engines = await client.list_engines()
    return [
        {
            "id": e.get("id"),
            "name": e.get("name"),
            "status": e.get("status"),
            "error": e.get("error"),
            "runningJobId": e.get("runningJobId"),
            "serverId": e.get("serverId"),
            "executionProfileId": e.get("executionProfileId"),
        }
        for e in engines
    ]


@mcp.tool()
async def list_jobs() -> dict:
    """List all non-archived jobs from Nuix Automate."""
    client = _get_client()
    return await client.list_jobs()


@mcp.tool()
async def cancel_job(job_id: str, command: str = "CANCEL") -> dict:
    """Cancel or control a job by sending a command to its execution endpoint."""
    client = _get_client()
    return await client.cancel_job(job_id, command=command)


@mcp.tool()
async def cancel_jobs_by_pattern(pattern: str, command: str = "CANCEL") -> dict:
    """Cancel multiple jobs matching a name pattern."""
    client = _get_client()
    return await client.cancel_jobs_by_pattern(pattern, command=command)


@mcp.tool()
async def suggest_openapi_endpoint(
    openapi_path: str,
    *,
    keywords: Optional[Iterable[str]] = None,
    limit: int = 3,
) -> dict:
    """Recommend Automate endpoints for downloading artifacts given an OpenAPI spec."""
    return await _suggest_openapi_endpoint(openapi_path, keywords=keywords, limit=limit)


@mcp.tool()
async def describe_openapi_call(
    openapi_path: str,
    *,
    keywords: Optional[Iterable[str]] = None,
    parameter_values: Optional[dict[str, str]] = None,
    base_url: Optional[str] = None,
) -> dict:
    """Read an OpenAPI document and propose a call that matches the supplied keywords."""
    return await _describe_openapi_call(
        openapi_path,
        keywords=keywords,
        parameter_values=parameter_values,
        base_url=base_url,
    )


@mcp.tool()
async def upload_rfn_workflow(
    rfn_file_path: str,
    *,
    library_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    enabled: bool = False,
) -> dict:
    """Deploy a workflow from an RFN file to Nuix Automate."""
    client = _get_client()

    # Resolve RFN file path
    rfn_path = Path(rfn_file_path)
    if not rfn_path.is_absolute():
        rfn_path = ROOT / rfn_file_path

    if not rfn_path.exists():
        return {
            "success": False,
            "errors": [f"RFN file not found: {rfn_path}"],
        }

    # Get library ID
    if not library_id:
        library_id = client._config.library_id
    if not library_id:
        return {
            "success": False,
            "errors": ["library_id is required"],
        }

    # Load RFN content
    try:
        rfn_content = rfn_path.read_text(encoding='utf-8')
    except Exception as e:
        return {
            "success": False,
            "errors": [f"Failed to read RFN file: {e}"],
        }

    # Extract workflow name for response
    import xml.etree.ElementTree as ET
    workflow_name = rfn_path.stem
    try:
        tree = ET.fromstring(rfn_content)
        name_elem = tree.find("name")
        if name_elem is not None and name_elem.text:
            workflow_name = name_elem.text
    except Exception:
        pass  # Use filename as fallback

    # Deploy workflow using new method
    try:
        result = await client.deploy_workflow_from_rfn(
            rfn_content=rfn_content,
            library_id=library_id,
            workflow_id=workflow_id,
            enabled=enabled,
        )

        response_workflow_id = (
            result.get("id")
            or result.get("workflowId")
            or result.get("workflow_id")
            or workflow_id
        )

        operations_count = len(result.get("operations", []))

        return {
            "success": True,
            "workflow_id": response_workflow_id,
            "workflow_name": workflow_name,
            "operations_count": operations_count,
            "enabled": enabled,
            "library_id": library_id,
            "action": "updated" if workflow_id else "created",
        }
    except Exception as e:
        return {
            "success": False,
            "workflow_name": workflow_name,
            "library_id": library_id,
            "workflow_id": workflow_id,
            "errors": [str(e)],
        }


@mcp.tool()
async def execute_session_query_v2(
    session_id: str,
    query: str,
    max_items: int = 1000,
    cache_key: Optional[str] = None,
    timeout_seconds: int = 30,
    priority: int = 1,
) -> dict:
    """Execute a query in a persistent session with v2 protocol features."""
    try:
        manager = _get_session_manager()
        session = manager.get_session(session_id)
        if not session:
            return {"error": f"Session {session_id} not found"}

        hints = {
            "cache_key": cache_key,
            "timeout_seconds": timeout_seconds,
            "priority": priority,
        }
        result = await manager.execute_search_v2(session, query, max_items, hints=hints)
        return result

    except Exception as exc:
        return {"error": f"Query execution failed: {exc}"}


@mcp.tool()
async def get_session_metrics(session_id: str) -> dict:
    """Get performance metrics for a persistent session."""
    try:
        manager = _get_session_manager()
        metrics = manager.get_session_metrics(session_id)
        if metrics is None:
            return {"error": f"Session {session_id} not found"}
        return metrics

    except Exception as exc:
        return {"error": f"Failed to get metrics: {exc}"}


@mcp.tool()
async def list_active_sessions_v2() -> dict:
    """List all active persistent sessions with their metadata."""
    try:
        manager = _get_session_manager()
        sessions = manager.list_active_sessions()
        return {"sessions": sessions, "count": len(sessions)}

    except Exception as exc:
        return {"error": f"Failed to list sessions: {exc}"}


@mcp.tool()
async def execute_batch_queries(
    session_id: str,
    queries: list[str],
    max_items: int = 1000,
    parallel: bool = False,
) -> dict:
    """Execute multiple queries in a single session (faster than individual calls)."""
    try:
        manager = _get_session_manager()
        session = manager.get_session(session_id)
        if not session:
            return {"error": f"Session {session_id} not found"}

        if parallel:
            import asyncio
            results = await asyncio.gather(
                *[manager.execute_search(session, q, max_items) for q in queries],
                return_exceptions=True,
            )
        else:
            results = []
            for query in queries:
                try:
                    result = await manager.execute_search(session, query, max_items)
                    results.append(result)
                except Exception as e:
                    results.append({"error": str(e), "query": query})

        return {"results": results, "count": len(results), "queries_count": len(queries)}

    except Exception as exc:
        return {"error": f"Batch execution failed: {exc}"}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

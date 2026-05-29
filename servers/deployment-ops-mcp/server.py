"""Deployment operations MCP server for DataExpert agentic AI.

Entry point for the dataexpert-deployment-ops-mcp package.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


ROOT = Path(__file__).resolve().parents[3]

# Load local secrets.env so the MCP server can access SSH and sudo credentials.
try:
    load_dotenv(ROOT / "security" / "secrets.env", override=False, interpolate=False)
except TypeError:
    load_dotenv(ROOT / "security" / "secrets.env", override=False)

mcp = FastMCP("deployment-ops")


def _read_inventory() -> Dict[str, Any]:
    path = ROOT / "security" / "deployment_inventory.yaml"
    if not path.exists():
        raise FileNotFoundError("security/deployment_inventory.yaml not found")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("deployment_inventory.yaml must be a mapping")
    return data


def _get_agenticdocker_env(data: Dict[str, Any]) -> Dict[str, Any]:
    for env in data.get("environments", []) or []:
        if env.get("name") == "agenticdocker":
            return env
    raise ValueError("agenticdocker environment not found in deployment inventory")


def _get_agenticdocker_host(env: Dict[str, Any]) -> str:
    host = env.get("host", {}) or {}
    ip = host.get("ip")
    if not ip:
        raise ValueError("agenticdocker host ip missing in deployment inventory")
    return str(ip)


def _get_agentic_chat_root(env: Dict[str, Any]) -> str:
    for service in env.get("services", []) or []:
        if service.get("name") != "agentic-chat":
            continue
        env_info = service.get("env", {}) or {}
        secrets_path = env_info.get("secrets") or env_info.get("non_secret")
        if secrets_path:
            return str(PurePosixPath(secrets_path).parents[1])
        exec_start = service.get("exec_start", "")
        if exec_start:
            exec_path = PurePosixPath(str(exec_start).split()[0])
            return str(exec_path.parents[2])
    raise ValueError("agentic-chat root path missing in deployment inventory")


def _find_ssh_executable() -> str:
    return shutil.which("ssh") or shutil.which("ssh.exe") or "ssh"


def _ssh_run(host: str, command: str, stdin_text: Optional[str] = None) -> Dict[str, Any]:
    key_path = ROOT / "security" / "agentic_autoinstall_key"
    if not key_path.exists():
        raise FileNotFoundError("security/agentic_autoinstall_key not found")
    ssh = _find_ssh_executable()
    args = [
        ssh,
        "-i",
        str(key_path),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        f"agentic@{host}",
        command,
    ]
    result = subprocess.run(
        args,
        input=stdin_text,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _get_sudo_password() -> str:
    return os.getenv("AUTOINSTALL_PASSWORD", "")


def _parse_kv_output(text: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


@mcp.tool()
async def get_deployment_inventory() -> Dict[str, Any]:
    """Return the deployment inventory for shared reference."""
    return _read_inventory()


@mcp.tool()
async def check_agenticdocker_status() -> Dict[str, Any]:
    """Check current deployed revision and service status on agenticdocker."""
    inventory = _read_inventory()
    env = _get_agenticdocker_env(inventory)
    host = _get_agenticdocker_host(env)
    app_root = _get_agentic_chat_root(env)
    command = (
        "bash -lc 'set -e; "
        f"APP_ROOT={app_root}; "
        "if [ -d \"$APP_ROOT/.git\" ]; then "
        "echo branch=$(git -C \"$APP_ROOT\" rev-parse --abbrev-ref HEAD); "
        "echo commit=$(git -C \"$APP_ROOT\" rev-parse HEAD); "
        "else "
        "echo branch=unknown; "
        "echo commit=unknown; "
        "fi; "
        "echo status=$(systemctl is-active agentic-chat); "
        "echo state=$(systemctl show -p ActiveState -p SubState agentic-chat | tr \"\\n\" \";\" )'"
    )
    result = _ssh_run(host, command)
    return {
        "host": host,
        "app_root": app_root,
        "result": result,
        "parsed": _parse_kv_output(result.get("stdout", "")),
    }


@mcp.tool()
async def deploy_agentic_chat(
    ref: str = "main",
    restart_service: bool = True,
    health_check: bool = True,
) -> Dict[str, Any]:
    """Update agentic-chat on agenticdocker to the given ref and restart."""
    inventory = _read_inventory()
    env = _get_agenticdocker_env(inventory)
    host = _get_agenticdocker_host(env)
    app_root = _get_agentic_chat_root(env)
    results: list[Dict[str, Any]] = []

    git_cmd = (
        "bash -lc 'set -e; "
        f"git -C {app_root} fetch origin {ref}; "
        f"git -C {app_root} checkout {ref}; "
        f"git -C {app_root} pull --ff-only origin {ref}'"
    )
    results.append({"step": "git_update", **_ssh_run(host, git_cmd)})

    if restart_service:
        password = _get_sudo_password()
        if not password:
            raise ValueError("AUTOINSTALL_PASSWORD not found in secrets.env")
        restart_cmd = "sudo -S systemctl restart agentic-chat"
        results.append({
            "step": "restart_service",
            **_ssh_run(host, restart_cmd, stdin_text=f"{password}\n"),
        })

    if health_check:
        health_cmd = "curl -fsS http://localhost:8000/health"
        results.append({"step": "health_check", **_ssh_run(host, health_cmd)})

    status = await check_agenticdocker_status()
    return {
        "host": host,
        "app_root": app_root,
        "results": results,
        "status": status,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

"""DataExpert vSphere Lab MCP server.

This server is the agent-facing contract for vSphere lab readiness. It accepts
structured topology payloads, resolves credential profile names to server-local
files, and delegates deterministic vSphere work to the provisioner CLI in the
DataExpert-vsphere-lab-automation repository.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


ROOT = Path(__file__).resolve().parents[2]

try:
    load_dotenv(ROOT / "security" / "secrets.env", override=False, interpolate=False)
except TypeError:
    load_dotenv(ROOT / "security" / "secrets.env", override=False)

mcp = FastMCP("dataexpert-vsphere-lab")

SERVER_NAME = "DataExpert vSphere Lab MCP"
SECRET_KEY_RE = re.compile(
    r"(password|passwd|passphrase|secret|token|private[_-]?key|ssh[_-]?key|credential|credentials)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CredentialProfile:
    name: str
    credentials: str = "security/vsphere.env"
    guest_credentials: str = "security/guest.env"
    ssh_credentials: str = "security/ssh.env"
    domain_credentials: str = "security/domain.env"
    playbook: str = ""
    datacenter: str = ""


@dataclass(frozen=True)
class ProvisionerResult:
    command: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    ok: bool


def _lab_repo() -> Path:
    configured = os.getenv("VSPHERE_LAB_REPO", "").strip()
    path = Path(configured) if configured else ROOT.parent / "DataExpert-vsphere-lab-automation"
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"VSPHERE_LAB_REPO does not exist or is not a directory: {resolved}")
    return resolved


def _run_root(lab_repo: Path) -> Path:
    configured = os.getenv("VSPHERE_LAB_RUN_ROOT", ".").strip() or "."
    return _repo_path(lab_repo, configured)


def _provisioner_bin() -> str:
    configured = os.getenv("VSPHERE_PROVISIONER_BIN", "provisioner").strip() or "provisioner"
    path = Path(configured)
    if not path.is_absolute() and ("/" in configured or "\\" in configured):
        return str((_lab_repo() / path).resolve())
    return configured


def _default_profile_name() -> str:
    return os.getenv("VSPHERE_LAB_DEFAULT_CREDENTIAL_PROFILE", "default").strip() or "default"


def _repo_path(lab_repo: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = lab_repo / path
    resolved = path.resolve()
    if resolved != lab_repo and lab_repo not in resolved.parents:
        raise ValueError(f"path must stay inside VSPHERE_LAB_REPO: {value}")
    return resolved


def _load_profiles() -> dict[str, CredentialProfile]:
    profiles: dict[str, CredentialProfile] = {"default": CredentialProfile(name="default")}
    raw = os.getenv("VSPHERE_LAB_CREDENTIAL_PROFILES", "").strip()
    if raw:
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError("VSPHERE_LAB_CREDENTIAL_PROFILES must be a JSON object")
        for name, values in loaded.items():
            if not isinstance(values, dict):
                raise ValueError(f"credential profile {name!r} must be a JSON object")
            profiles[str(name)] = CredentialProfile(
                name=str(name),
                credentials=str(values.get("credentials", "security/vsphere.env")),
                guest_credentials=str(values.get("guest_credentials", "security/guest.env")),
                ssh_credentials=str(values.get("ssh_credentials", "security/ssh.env")),
                domain_credentials=str(values.get("domain_credentials", "security/domain.env")),
                playbook=str(values.get("playbook", "")),
                datacenter=str(values.get("datacenter", "")),
            )
    return profiles


def _profile(name: str | None) -> CredentialProfile:
    selected = (name or "").strip() or _default_profile_name()
    allowed_raw = os.getenv("VSPHERE_LAB_ALLOWED_CREDENTIAL_PROFILES", "").strip()
    allowed = {item.strip() for item in allowed_raw.split(",") if item.strip()}
    if allowed and selected not in allowed:
        raise ValueError(f"credential profile {selected!r} is not allowed on this MCP server")
    profiles = _load_profiles()
    if selected not in profiles:
        raise ValueError(f"credential profile {selected!r} is not configured on this MCP server")
    return profiles[selected]


def _assert_topology_payload(topology: dict[str, Any]) -> None:
    if not isinstance(topology, dict):
        raise ValueError("topology must be a structured JSON object")
    if not str(topology.get("name", "")).strip():
        raise ValueError("topology.name is required")
    _reject_secret_fields(topology, "topology")


def _reject_secret_fields(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if SECRET_KEY_RE.search(str(key)):
                raise ValueError(f"{child_path} is not allowed in MCP topology payloads")
            _reject_secret_fields(child, child_path)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, f"{path}[{index}]")


def _topology_name(topology: dict[str, Any]) -> str:
    _assert_topology_payload(topology)
    return str(topology["name"]).strip()


def _confirmation(tool: str, topology: dict[str, Any], actual: str) -> None:
    expected = f"{tool}:{_topology_name(topology)}"
    if actual != expected:
        raise ValueError(f"confirmation must be exactly {expected!r}")


def _write_topology_payload(lab_repo: Path, run_root: Path, topology: dict[str, Any]) -> Path:
    _assert_topology_payload(topology)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", _topology_name(topology)).strip("-") or "topology"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = run_root / ".mcp-topologies"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{safe_name}-{uuid.uuid4().hex[:8]}.json"
    if path.resolve() != path and lab_repo not in path.resolve().parents:
        raise ValueError("generated topology path escaped VSPHERE_LAB_REPO")
    path.write_text(json.dumps(topology, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _run_provisioner(lab_repo: Path, args: list[str]) -> ProvisionerResult:
    command = [_provisioner_bin(), *args]
    result = subprocess.run(
        command,
        cwd=lab_repo,
        text=True,
        capture_output=True,
        check=False,
    )
    return ProvisionerResult(
        command=command,
        cwd=str(lab_repo),
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        ok=result.returncode == 0,
    )


def _base_args(command: str, topology_path: Path, run_root: Path) -> list[str]:
    return [command, "-topology", str(topology_path), "-run-root", str(run_root)]


def _profile_args(lab_repo: Path, profile: CredentialProfile, *, include_guest: bool, include_baseline: bool, datacenter: str) -> list[str]:
    args = ["-credentials", str(_repo_path(lab_repo, profile.credentials))]
    if include_guest:
        args.extend(["-guest-credentials", str(_repo_path(lab_repo, profile.guest_credentials))])
    selected_datacenter = datacenter or profile.datacenter
    if selected_datacenter:
        args.extend(["-datacenter", selected_datacenter])
    if include_baseline and profile.playbook:
        args.extend(
            [
                "-playbook",
                str(_repo_path(lab_repo, profile.playbook)),
                "-ssh-credentials",
                str(_repo_path(lab_repo, profile.ssh_credentials)),
                "-domain-credentials",
                str(_repo_path(lab_repo, profile.domain_credentials)),
            ]
        )
    return args


def _structured_response(operation: str, topology: dict[str, Any], result: ProvisionerResult, run_root: Path) -> dict[str, Any]:
    evidence_dir = _extract_evidence_dir(result.stdout, run_root)
    evidence = _read_evidence(evidence_dir) if evidence_dir else {}
    return {
        "server": SERVER_NAME,
        "operation": operation,
        "topology_name": _topology_name(topology),
        "ok": result.ok,
        "exit_code": result.exit_code,
        "command": _public_command(result.command),
        "cwd": result.cwd,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "run_evidence": evidence,
        "inventory": _inventory(evidence),
        "resolved_vm_state": _resolved_vm_state(evidence),
        "ssh_readiness": _ssh_readiness(evidence),
        "storage_readiness": _storage_readiness(evidence),
    }


def _extract_evidence_dir(stdout: str, run_root: Path) -> Path | None:
    for line in stdout.splitlines():
        marker = "run evidence written to "
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].strip().strip('"')
        path = Path(raw)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        resolved = path.resolve()
        if resolved.exists():
            return resolved
    return None


def _public_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for item in command:
        if redact_next:
            redacted.append("<server-local-profile-path>")
            redact_next = False
            continue
        redacted.append(item)
        if item in {
            "-credentials",
            "-guest-credentials",
            "-ssh-credentials",
            "-domain-credentials",
            "-playbook",
        }:
            redact_next = True
    return redacted


def _read_evidence(evidence_dir: Path) -> dict[str, Any]:
    files: list[dict[str, str]] = []
    records: dict[str, Any] = {}
    inventory_content = ""
    inventory_path = evidence_dir / "inventory.yaml"

    for path in sorted(evidence_dir.iterdir()):
        if not path.is_file():
            continue
        files.append({"name": path.name, "path": str(path)})
        if path.suffix == ".json":
            try:
                records[path.stem] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                records[path.stem] = {"parse_error": str(exc)}

    if inventory_path.exists():
        inventory_content = inventory_path.read_text(encoding="utf-8")

    return {
        "dir": str(evidence_dir),
        "files": files,
        "records": records,
        "inventory_path": str(inventory_path) if inventory_path.exists() else "",
        "inventory_content": inventory_content,
    }


def _inventory(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": evidence.get("inventory_path", ""),
        "content": evidence.get("inventory_content", ""),
        "record": evidence.get("records", {}).get("inventory", {}),
    }


def _resolved_vm_state(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    records = evidence.get("records", {})
    resolved = records.get("resolved-topology", {})
    states: dict[str, dict[str, Any]] = {}
    # The full resolved-topology VM object is forwarded under "resolved", so any
    # infrastructure field the provisioner records on the VM (including the new
    # os_intent and shared_storage handoff metadata) flows through automatically
    # without needing a per-field allowlist here.
    for vm in resolved.get("vms", []) if isinstance(resolved, dict) else []:
        if isinstance(vm, dict) and vm.get("name"):
            states[str(vm["name"])] = {"name": vm["name"], "resolved": vm}

    for key, record in records.items():
        if not isinstance(record, dict):
            continue
        vm_name = str(record.get("vm_name", ""))
        if not vm_name:
            continue
        entry = states.setdefault(vm_name, {"name": vm_name})
        if key.startswith("clone-"):
            entry["clone"] = record
        elif key.startswith("reconcile-"):
            entry["reconcile"] = record
        elif key.startswith("ipdisc-"):
            entry["ip_discovery"] = record
        elif key.startswith("ssh-"):
            entry["ssh"] = record
        elif key.startswith("netmove-"):
            entry["network_transition"] = record
        elif key.startswith("finalplacement-"):
            entry["final_placement"] = record
        elif key.startswith("bootstrap-"):
            entry["bootstrap"] = record

    return list(states.values())


def _ssh_readiness(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    records = evidence.get("records", {})
    readiness = []
    for key, record in records.items():
        if key.startswith("ssh-") and isinstance(record, dict):
            readiness.append(record)
    return readiness


def _storage_readiness(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    # The provisioner writes a single storage-readiness.json record whose body is
    # a JSON array of per-mount readiness entries (states: pending-os-ops /
    # verified / missing / external-endpoint). Surface it as a list, tolerating
    # absence or an unexpected shape.
    record = evidence.get("records", {}).get("storage-readiness")
    if isinstance(record, list):
        return [entry for entry in record if isinstance(entry, dict)]
    return []


def _run_topology_command(
    operation: str,
    command: str,
    topology: dict[str, Any],
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    lab_repo = _lab_repo()
    run_root = _run_root(lab_repo)
    topology_path = _write_topology_payload(lab_repo, run_root, topology)
    args = [*_base_args(command, topology_path, run_root), *(extra_args or [])]
    result = _run_provisioner(lab_repo, args)
    return _structured_response(operation, topology, result, run_root)


@mcp.tool()
async def vsphere_lab_plan(topology: dict[str, Any]) -> dict[str, Any]:
    """Resolve a JSON topology payload and write offline run evidence."""
    return _run_topology_command("vsphere_lab_plan", "plan", topology)


@mcp.tool()
async def vsphere_lab_preflight(topology: dict[str, Any], credential_profile: str = "") -> dict[str, Any]:
    """Run capacity preflight for a JSON topology payload using server-local credentials."""
    _profile(credential_profile)
    return _run_topology_command("vsphere_lab_preflight", "preflight", topology)


@mcp.tool()
async def vsphere_lab_apply(
    topology: dict[str, Any],
    confirmation: str,
    credential_profile: str = "",
    allow_live_vsphere: bool = False,
    datacenter: str = "",
    run_os_baseline: bool = False,
) -> dict[str, Any]:
    """Provision or reconcile lab VMs. Product deployment remains outside this MCP."""
    if not allow_live_vsphere:
        raise ValueError("allow_live_vsphere must be true for live vSphere mutation")
    _confirmation("vsphere_lab_apply", topology, confirmation)
    lab_repo = _lab_repo()
    profile = _profile(credential_profile)
    args = [
        "-live-vsphere",
        *_profile_args(
            lab_repo,
            profile,
            include_guest=True,
            include_baseline=run_os_baseline,
            datacenter=datacenter,
        ),
    ]
    return _run_topology_command("vsphere_lab_apply", "apply", topology, args)


@mcp.tool()
async def vsphere_lab_ensure_ssh_ready(
    topology: dict[str, Any],
    confirmation: str,
    credential_profile: str = "",
    allow_live_vsphere: bool = False,
    datacenter: str = "",
) -> dict[str, Any]:
    """Provision/reconcile lab VMs until guest IPs are discovered and SSH is reachable."""
    if not allow_live_vsphere:
        raise ValueError("allow_live_vsphere must be true for live vSphere mutation")
    _confirmation("vsphere_lab_ensure_ssh_ready", topology, confirmation)
    lab_repo = _lab_repo()
    profile = _profile(credential_profile)
    args = [
        "-live-vsphere",
        *_profile_args(lab_repo, profile, include_guest=True, include_baseline=False, datacenter=datacenter),
    ]
    return _run_topology_command("vsphere_lab_ensure_ssh_ready", "apply", topology, args)


@mcp.tool()
async def vsphere_lab_inventory(topology: dict[str, Any], run_evidence_dir: str = "") -> dict[str, Any]:
    """Return inline inventory content from run evidence for this topology."""
    _assert_topology_payload(topology)
    lab_repo = _lab_repo()
    run_root = _run_root(lab_repo)
    evidence_dir = _select_evidence_dir(run_root, topology, run_evidence_dir)
    evidence = _read_evidence(evidence_dir) if evidence_dir else {}
    return {
        "server": SERVER_NAME,
        "operation": "vsphere_lab_inventory",
        "topology_name": _topology_name(topology),
        "ok": bool(evidence.get("inventory_content")),
        "run_evidence": evidence,
        "inventory": _inventory(evidence),
        "resolved_vm_state": _resolved_vm_state(evidence),
        "ssh_readiness": _ssh_readiness(evidence),
        "storage_readiness": _storage_readiness(evidence),
    }


@mcp.tool()
async def vsphere_lab_move_to_final(
    topology: dict[str, Any],
    confirmation: str,
    credential_profile: str = "",
    datacenter: str = "",
) -> dict[str, Any]:
    """Move VMs from bootstrap network to final network and verify placement."""
    _confirmation("vsphere_lab_move_to_final", topology, confirmation)
    lab_repo = _lab_repo()
    profile = _profile(credential_profile)
    args = _profile_args(lab_repo, profile, include_guest=False, include_baseline=False, datacenter=datacenter)
    return _run_topology_command("vsphere_lab_move_to_final", "move-to-final", topology, args)


@mcp.tool()
async def vsphere_lab_ensure_ready(
    topology: dict[str, Any],
    confirmation: str,
    credential_profile: str = "",
    allow_live_vsphere: bool = False,
    datacenter: str = "",
    run_os_baseline: bool = False,
) -> dict[str, Any]:
    """Convenience workflow: ensure SSH-ready lab VMs, then move them to final network."""
    if not allow_live_vsphere:
        raise ValueError("allow_live_vsphere must be true for live vSphere mutation")
    _confirmation("vsphere_lab_ensure_ready", topology, confirmation)
    lab_repo = _lab_repo()
    profile = _profile(credential_profile)
    apply_args = [
        "-live-vsphere",
        *_profile_args(
            lab_repo,
            profile,
            include_guest=True,
            include_baseline=run_os_baseline,
            datacenter=datacenter,
        ),
    ]
    apply_result = _run_topology_command("vsphere_lab_ensure_ready.apply", "apply", topology, apply_args)
    if not apply_result["ok"]:
        return {
            "server": SERVER_NAME,
            "operation": "vsphere_lab_ensure_ready",
            "ok": False,
            "topology_name": _topology_name(topology),
            "apply": apply_result,
            "move_to_final": None,
        }
    move_args = _profile_args(lab_repo, profile, include_guest=False, include_baseline=False, datacenter=datacenter)
    move_result = _run_topology_command("vsphere_lab_ensure_ready.move_to_final", "move-to-final", topology, move_args)
    return {
        "server": SERVER_NAME,
        "operation": "vsphere_lab_ensure_ready",
        "ok": bool(apply_result["ok"] and move_result["ok"]),
        "topology_name": _topology_name(topology),
        "apply": apply_result,
        "move_to_final": move_result,
        "inventory": move_result.get("inventory") or apply_result.get("inventory"),
        "resolved_vm_state": move_result.get("resolved_vm_state") or apply_result.get("resolved_vm_state"),
        "ssh_readiness": apply_result.get("ssh_readiness", []),
        "storage_readiness": move_result.get("storage_readiness") or apply_result.get("storage_readiness", []),
    }


def _select_evidence_dir(run_root: Path, topology: dict[str, Any], requested: str) -> Path | None:
    if requested:
        path = Path(requested).expanduser()
        if not path.is_absolute():
            path = run_root / requested
        resolved = path.resolve()
        root = run_root.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"run_evidence_dir must stay inside VSPHERE_LAB_RUN_ROOT: {resolved}")
        if not resolved.is_dir():
            raise FileNotFoundError(f"run_evidence_dir does not exist: {resolved}")
        return resolved

    runs = run_root / "runs"
    if not runs.is_dir():
        return None
    topology_name = _topology_name(topology)
    candidates: list[Path] = []
    for path in runs.iterdir():
        inv = path / "inventory.json"
        if not inv.is_file():
            continue
        try:
            record = json.loads(inv.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if record.get("topology_name") == topology_name:
            candidates.append(path)
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

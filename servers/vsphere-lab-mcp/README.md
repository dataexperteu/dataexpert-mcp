# DataExpert vSphere Lab MCP

Agent-facing MCP contract for DataExpert vSphere lab provisioning and guest
readiness. This server does not implement raw vSphere clone, power, network,
capacity, guest-operation or evidence logic. It delegates that work to the
deterministic provisioner in `../DataExpert-vsphere-lab-automation`.

## Contract

Public tools use the `vsphere_lab_*` prefix:

- `vsphere_lab_plan`
- `vsphere_lab_preflight`
- `vsphere_lab_apply`
- `vsphere_lab_ensure_ssh_ready`
- `vsphere_lab_inventory`
- `vsphere_lab_move_to_final`
- `vsphere_lab_ensure_ready`

All topology input is a structured JSON payload matching the provisioner topology
model. The MCP request must not pass topology file paths, vSphere secrets, SSH
secrets, domain secrets or credential file paths.

Live mutation tools require both:

- an allowed `credential_profile`
- an exact confirmation token

Confirmation tokens:

```text
vsphere_lab_apply:<topology.name>
vsphere_lab_ensure_ssh_ready:<topology.name>
vsphere_lab_move_to_final:<topology.name>
vsphere_lab_ensure_ready:<topology.name>
```

Results are machine-readable and include provisioner stdout/stderr, resolved VM
state from Run Evidence, SSH readiness records, inline Ansible inventory content
when generated, and Run Evidence file references.

## Boundary

This MCP stops at lab VM readiness:

- validates and plans topology payloads
- runs vSphere preflight/provision/reconcile through the provisioner
- verifies guest IP and SSH readiness
- returns inventory and Run Evidence for consuming projects
- moves VMs from bootstrap to final lab network when explicitly confirmed

It does not deploy or update agentic-chat, install product components, restart
application services, or own product-specific Ansible. Agentic-chat day-2
deployment belongs to
[`servers/agentic-chat-deploy-mcp`](../agentic-chat-deploy-mcp).

The optional `run_os_baseline` flag only invokes the provisioner's generic OS
readiness baseline from the lab automation repo. It is not a product deployment
hook.

## Configuration

Set these in `security/secrets.env` at the `dataexpert-mcp` repo root:

```text
VSPHERE_LAB_REPO=../DataExpert-vsphere-lab-automation
VSPHERE_PROVISIONER_BIN=provisioner
VSPHERE_LAB_RUN_ROOT=.
VSPHERE_LAB_DEFAULT_CREDENTIAL_PROFILE=default
VSPHERE_LAB_ALLOWED_CREDENTIAL_PROFILES=default
```

`VSPHERE_LAB_REPO` defaults to the sibling
`../DataExpert-vsphere-lab-automation`. `VSPHERE_PROVISIONER_BIN` defaults to
`provisioner`.

Credential profiles are server-local mappings from non-secret profile names to
ignored files in the lab automation repo. The default profile uses:

```text
security/vsphere.env
security/guest.env
security/ssh.env
security/domain.env
```

To override or add profiles, set `VSPHERE_LAB_CREDENTIAL_PROFILES` to JSON:

```json
{
  "default": {
    "credentials": "security/vsphere.env",
    "guest_credentials": "security/guest.env",
    "ssh_credentials": "security/ssh.env",
    "domain_credentials": "security/domain.env",
    "playbook": "playbooks/linux-baseline.yml",
    "datacenter": ""
  }
}
```

Do not put raw secret values in MCP requests or committed files.

## Source-First Setup

Clone the lab automation repo beside this repo and build the provisioner locally:

```bash
cd ../DataExpert-vsphere-lab-automation
go build -o bin/provisioner ./cmd/provisioner
```

Then point this MCP at the built binary:

```text
VSPHERE_PROVISIONER_BIN=bin/provisioner
```

For local multi-repo Go work, create an uncommitted workspace in the lab
automation repo:

```bash
go work init .
go work use .
```

Keep `go.work`, `go.work.sum`, credential files and generated `runs/` evidence
out of git.

## Run Locally

```bash
cd servers/vsphere-lab-mcp
python -m pip install -e .
dataexpert-vsphere-lab-mcp
```

Use `examples/minimal-topology.json` as a request template only. Authoritative
project topologies belong in the consuming project repository that calls this
MCP.

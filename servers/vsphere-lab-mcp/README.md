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
state from Run Evidence, SSH readiness records, storage readiness records, inline
Ansible inventory content when generated, and Run Evidence file references. The
resolved VM state forwards every resolved-topology field, so infrastructure
metadata such as `os_intent` and the `shared_storage` handoff flow through
automatically per VM.

## Topology flexibility

The provisioner topology model supports flexible, infrastructure-level shaping.
The MCP forwards these fields verbatim — it adds no schema beyond requiring
`name` and rejecting secret-looking keys.

- **`defaults` block + per-VM overrides.** Set repo-wide infrastructure values
  in `defaults`, then override any of them on individual VMs:
  `guest_os`, `source_template`, `cpu`, `memory_mb`, `disk_gb`, `host`,
  `datastore`, `bootstrap_network`, `final_network`, and `ansible_vars`.
- **`guest_os`** (`linux` | `windows`): selects the guest operating system
  family for a VM (defaults plus per-VM override).
- **`source_template` override / mixed Linux + Windows.** Each VM may override
  the source template, so a single topology can mix Linux and Windows guests by
  pairing the matching `guest_os` with a per-VM `source_template`.
- **`os_intent`** (`rhel9` | `ubuntu-interim` | unset): visibility metadata that
  declares the OS/template target. RHEL9 is the target; `ubuntu-interim` is the
  explicit interim until a RHEL9 template exists. It is orthogonal to `guest_os`
  and `source_template`. Available in `defaults` and per VM.

### RHEL 9 topologies

Setting `os_intent: "rhel9"` selects the RHEL 9 template path. The target
template **`DX-LAB-RHEL9-TEMPLATE`** is **built and available** (RHEL 9.8, built
2026-06-25 in the lab vCenter), so a `rhel9` topology sets
`source_template: "DX-LAB-RHEL9-TEMPLATE"` directly — as shown in
`examples/rhel9-topology.json` (a neutral `compute` / `storage` demonstration).

`os_intent` and `source_template` stay distinct on purpose (the guardrail):
`os_intent` records the intended OS target while `source_template` names the
template the provisioner actually clones. If the RHEL 9 template is ever
unavailable, a topology may keep `os_intent: "rhel9"` and set `source_template`
to the interim Ubuntu template (e.g. `Neo UBUNTU 24.04`) as an explicit
fallback — never a silent default.

### RHEL 9 SSH access — read this before you provision (avoids the SSH dead-end)

How to log into the RHEL 9 VMs you provision, and how to keep it secure:

- **Login is `dxadmin` over SSH with the lab automation key — key-only.** The
  `DX-LAB-RHEL9-TEMPLATE` ships `dxadmin` with the lab automation **public** key
  (`csm-automation`) in `authorized_keys`. `root` and the `dxadmin` password are
  **locked** — there is **no password login** and no root SSH. Use the matching
  **private** key (the lab `csm_deploy_key`). Do not look for a password.
- **The private key is server-local, never in MCP payloads.** Select it through a
  `credential_profile` / the provisioner's `security/ssh.env`
  (`SSH_USER=dxadmin`, `SSH_KEY_PATH=...`). **Never** put SSH keys, passwords, or
  any secret in a topology payload or MCP request — the server rejects
  secret-looking keys, and that is the intended security boundary.
- **Let the provisioner make VMs SSH-ready; don't hand-roll it.** The
  apply/ensure-ssh-ready tools discover the guest IP via VMware tools and verify
  SSH before reporting readiness. The OS baseline (run only when you ask for it)
  sets unique hostnames/identity over that SSH credential.
- **Do NOT chase a key on the OEMDRV ISO.** `OEMDRV` is the *kickstart* medium
  used only during the template install; it is **not** a cloud-init datasource
  and clones don't even have it attached. There is no per-VM key hidden there.
- **Recovery if a clone has no way in** (e.g. provisioned before the template was
  keyed): attach a cloud-init **NoCloud** seed — a CD labeled `cidata` containing
  `meta-data` (a fresh `instance-id`) and `user-data` (`#cloud-config` with a
  `runcmd` that writes the public key to `/home/dxadmin/.ssh/authorized_keys`,
  `usermod -U dxadmin`, `restorecon`) — then power-cycle. cloud-init runs as root
  and injects the key without any login. This needs vSphere access (a human with
  credentials), not an MCP call.
- **`shared_storage`** (per-VM block): generic OS-ops storage handoff metadata
  with `mount_path` (string), `required_gb` (int), and `provision` (bool;
  `false` = external endpoint the lab consumes, `true` = the lab provisions the
  backing storage VM).
- **`role` / `group`** (per VM): generic grouping fields that drive a
  role-grouped Ansible inventory, including an `all.vars.lab_role_hosts` map
  (role -> sorted host list) and per-host `lab_os_intent`,
  `lab_storage_mount_path`, `lab_storage_required_gb`, and
  `lab_storage_provision` vars.

The structured result also surfaces these: each resolved VM carries its
`os_intent` and `shared_storage` handoff (via `resolved_vm_state`), the
`storage_readiness` section reports per-mount readiness state
(`pending-os-ops` / `verified` / `missing` / `external-endpoint`), and the
inline inventory exposes the `lab_role_hosts` / `lab_*` vars.

Application-specific topology — product roles, application configuration, worker
counts, and any product or component names — belongs in the consuming project's
topology payload and repository, **not** in this MCP's contract or examples.
This MCP and its examples stay technology-agnostic and model only
infrastructure concerns. See `examples/flexible-topology.json` for a neutral
demonstration using `compute` / `storage` roles.

## Boundary

This MCP stops at lab VM readiness:

- validates and plans topology payloads
- runs vSphere preflight/provision/reconcile through the provisioner
- verifies guest IP and SSH readiness
- returns inventory and Run Evidence for consuming projects
- moves VMs from bootstrap to final lab network when explicitly confirmed

It does not deploy, update, or install product components, restart application
services, or own product-specific Ansible.

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
../DataExpert-vsphere-lab-automation/security/vsphere.env
../DataExpert-vsphere-lab-automation/security/guest.env
../DataExpert-vsphere-lab-automation/security/ssh.env
../DataExpert-vsphere-lab-automation/security/domain.env
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

### Credential Files

Create the credential files in the lab automation repo, not in this MCP repo:

```bash
cd ../DataExpert-vsphere-lab-automation
mkdir -p security
```

`security/vsphere.env` is required for live vSphere preflight, apply, and
final-network moves:

```text
VSPHERE_HOST=vcenter.example.local
VSPHERE_USER=administrator@vsphere.local
VSPHERE_PASS=replace-with-local-secret
```

`security/guest.env` is required when live apply needs VMware Guest Operations:

```text
GUEST_USER=local-vm-admin
GUEST_PASS=replace-with-local-secret
```

`security/ssh.env` is only needed when `run_os_baseline=true`:

```text
SSH_USER=local-vm-admin
SSH_KEY_PATH=C:\Users\you\.ssh\lab_vm_key
# Or use SSH_PASS instead of SSH_KEY_PATH:
# SSH_PASS=replace-with-local-secret
```

`security/domain.env` is only needed when `run_os_baseline=true` and the OS
baseline joins/configures a domain:

```text
DOMAIN_USER=domain-join-user
DOMAIN_PASS=replace-with-local-secret
```

MCP calls do not pass these paths or values. They pass the profile name:

```json
{
  "credential_profile": "default",
  "allow_live_vsphere": true,
  "confirmation": "vsphere_lab_apply:example-vsphere-lab"
}
```

Do not put raw secret values in MCP requests or committed files. The
`security/` directories are ignored and should stay local to each machine.

## Source-First Setup

Prerequisite: Go 1.24+ installed from the official Go distribution at
`https://go.dev/dl/` or another verified package source.

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

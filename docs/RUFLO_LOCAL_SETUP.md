# Ruflo local connection repair

Verified on Almog's Mac on 2026-10-11. This is a local Codex/MCP repair;
it does not change JobPilot's production dependencies or deployment.

## Failure and repair

Codex already had a `ruflo` MCP registration, but its logs showed startup
failures (`No such file or directory` and a closed initialize connection).
Both the global registration and project `.mcp.json` launched
`npx -y ruflo@latest` without a fixed Node executable. The shared npm execution
cache also contained incomplete packages: required package manifests were
missing, so Ruflo could list tools while its memory backend failed.

The local runtime now lives in `.claude-flow/runtime-3.47.0`. It contains the
already installed Ruflo and `@claude-flow/cli` versions, both **3.47.0**.
Missing required packages were restored from local npm archives after checking
their SHA-512 checksums against the existing lockfile. No package installation
scripts ran and no dependency version was upgraded.

The seven restored locked packages were:

| Package | Version |
| --- | --- |
| `@claude-flow/security` | `3.0.0-alpha.12` |
| `@claude-flow/shared` | `3.0.0-alpha.7` |
| `@hono/node-server` | `2.1.1` |
| `agentdb` | `3.0.0-alpha.20` |
| `content-disposition` | `1.1.0` |
| `express` | `5.2.1` |
| `express-rate-limit` | `8.7.0` |

`runtime-origin.json` inside that directory records the source, lockfile digest,
and restored package versions. The isolated runtime avoids depending on a
mutable shared `npx` cache. Existing memory databases and WAL files were
preserved; no reset, forced initialization, or manual checkpoint was performed.

## Current local configuration

`~/.codex/config.toml` now uses this server transport:

```toml
[mcp_servers.ruflo]
command = "/Users/AlmogKarif/.nvm/versions/node/v22.12.0/bin/node"
args = ["/Users/AlmogKarif/Downloads/jobpilot/.claude-flow/runtime-3.47.0/node_modules/@claude-flow/cli/bin/cli.js", "mcp", "start"]
cwd = "/Users/AlmogKarif/Downloads/jobpilot"
startup_timeout_sec = 30
```

The existing Ruflo environment, tool approval settings, and plugin settings
were preserved. The server environment still limits agents to four and uses
the `hierarchical-mesh` topology. Project `.mcp.json` uses the same absolute
Node executable and CLI path. Launch that project configuration from JobPilot's
directory so it uses the existing project memory location.

Backups were saved with mode `600` before configuration changes:

- `~/.codex/config.toml.ruflo-backup-20261011T012719`
- `.claude-flow/diagnostics/mcp-project-before-20261011T012719.json`

The runtime, backups, and project `.mcp.json` are ignored by Git. These absolute
paths are specific to this Mac; moving the repository or removing Node 22.12.0
requires updating the corresponding local MCP registration.

## Verification

The following checks passed against the isolated runtime:

- Fresh stdio MCP initialization took approximately 0.14 seconds, produced no
  non-JSON stdout, and listed **90 tools**, including memory and orchestration.
- A diagnostic `memory_store` created a local 384-dimensional embedding;
  `memory_retrieve` returned the exact value and `memory_search` found its key.
- A second fresh MCP process retrieved and searched the persisted value.
- A real Codex **0.151.0** app-server client loaded the saved configuration
  without Ruflo command overrides. Its ephemeral thread reported Ruflo as
  `connected`, exposed 90 tools, and successfully called native MCP
  `memory_store`, `memory_retrieve`, and `memory_search`.
- A second independent Codex client retrieved and searched the first client's
  value. No model request or persistent conversation was started.
- The isolated runtime had zero missing non-optional package manifests from
  its lockfile after these checks.

The synthetic values use the namespace `jobpilot-local-diagnostics` with a
one-hour TTL. A concise reusable repair note was also stored and retrieved in
namespace `jobpilot`, key `ruflo-local-runtime-repair-20261011`.
Existing user processes were not terminated. No production
database, Storage download, employer application, commit, or push was involved.

On October 12 the ongoing Codex connection exposed native Ruflo tools, and a
memory write persisted successfully. Its embedding service reported a mock
fallback, so semantic retrieval in that connection remains unverified. The
fresh-client checks above verified real embeddings on October 11; transport
availability alone does not establish embedding health in another process.
Codex documents the
MCP configuration fields and connection management in its
[official MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

`codex mcp list` can check registration. A listed registration alone does not
prove the server initialized or that its memory backend works; verify actual
tool calls when diagnosing future connection failures.

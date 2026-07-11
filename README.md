# Taproom

Taproom discovers portable agent capabilities without owning them. It indexes
skill collections and MCP server registries, exposes skills through standard
FastMCP resources, and provides a local CLI for explicit installation.

The included development defaults discover sibling checkouts of `skill-tap`,
`skill-tap-private`, `mcp-tap`, and `mcp-tap-private`.

## Architecture

- The hosted FastMCP service searches and serves capability metadata.
- FastMCP's `SkillsDirectoryProvider` exposes `skill://<name>/SKILL.md`, a
  generated manifest, and supporting files.
- A small MJS CLI performs local filesystem changes, verifies SHA-256 hashes,
  and records installed files in `.taproom.lock`.
- MCP servers are searchable and inspectable. Automatic MCP configuration is
  intentionally deferred until client-specific changes and execution consent
  have a clear contract.

## Run the service

Requires Python 3.11+, `uv`, and FastMCP 3.4.x.

```sh
uv run taproom-server
```

The MCP endpoint is `http://127.0.0.1:8768/mcp`. The CLI-facing HTTP API is
under `http://127.0.0.1:8768/api/v1/`.

Override discovery roots with path-separated `name=/absolute/path` entries:

```sh
TAPROOM_SKILL_ROOTS='public=/srv/skills:private=/srv/private-skills' \
TAPROOM_MCP_ROOTS='public=/srv/mcp-servers' \
uv run taproom-server
```

Set `TAPROOM_HOST` or `TAPROOM_PORT` to override the default bind address.

## Use the local CLI

The CLI has no npm dependencies and requires Node.js 20+.

```sh
node bin/taproom.mjs search "understand an inherited codebase"
node bin/taproom.mjs info skilltap:skill:codebase-archeology
node bin/taproom.mjs add skilltap:skill:codebase-archeology --project .
node bin/taproom.mjs add skilltap:skill:codebase-archeology --global
```

Project installs go to `<project>/.agents/skills/`. Global installs default to
`~/.agents/skills/`; set `TAPROOM_SKILL_HOME` to target another agent's skill
directory. Existing skills are never replaced unless `--force` is supplied.

## MCP tools

- `search_capabilities(query, kind?, limit?)`
- `inspect_capability(capability_id)`

Skills are also available through FastMCP's standard skill resources. Search
is implemented over capability metadata because FastMCP's BM25 search transform
indexes tools rather than resources.

## Test

```sh
uv run python -m unittest discover -s tests
npm test
```

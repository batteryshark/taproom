# Taproom

<p align="center">
  <img src="assets/taproom-480.png" width="480" alt="Taproom — a 1950s comic-book robot serving Skill and MCP capability cards">
</p>

Taproom discovers portable agent capabilities without owning them. It indexes
skill collections and MCP server registries, exposes skills through standard
FastMCP resources, and provides a local CLI for explicit installation.

The development defaults discover sibling checkouts of the public SkillTap and
MCP Tap collections. A `taproom.toml` file can register any number of named
public or private taps, each containing multiple skill and MCP sources. Private
collections are never loaded implicitly.

## Architecture

- The hosted FastMCP service searches and serves capability metadata.
- FastMCP's skill provider exposes a namespaced `skill://` resource, generated
  manifest, and supporting files for every indexed skill.
- A small MJS CLI performs local filesystem changes, verifies SHA-256 hashes,
  and records installed files in `.taproom.lock`.
- MCP packages are searchable, inspectable, hash-verifiable, and fetchable.
  Automatic activation requires declared host requirements and a passing local
  doctor check.

## Quickstart

Requires Python 3.11+, `uv`, and FastMCP 3.4.x.

```sh
git clone https://github.com/batteryshark/taproom.git
git clone https://github.com/batteryshark/skills-tap.git skill-tap
cd taproom
uv sync
uv run taproom-server
```

The MCP endpoint is `http://127.0.0.1:8768/mcp`. The CLI-facing HTTP API is
under `http://127.0.0.1:8768/api/v1/`.

## Configure taps

Copy [`taproom.example.toml`](taproom.example.toml) to the ignored local file
`taproom.toml`, then enable and edit the taps available on that host:

```sh
cp taproom.example.toml taproom.toml
```

Each tap has a stable name and visibility. Sources inside it have their own
names, kinds, and roots:

```toml
version = 1

[[taps]]
name = "private"
visibility = "private"

[[taps.sources]]
name = "skilltap"
kind = "skill"
path = "../skill-tap-private/skills"

[[taps.sources]]
name = "rekit"
kind = "skill"
path = "../../reverse-engineering-tools/rekit-private/skills"

[[taps.sources]]
name = "rekit"
kind = "mcp"
path = "../../reverse-engineering-tools/rekit-private/mcp-servers"
```

Relative source paths resolve from the config file. Set `TAPROOM_CONFIG` to use
a config stored elsewhere. The older `TAPROOM_SKILL_ROOTS` and
`TAPROOM_MCP_ROOTS` variables remain available for a single compatibility tap.
Set `TAPROOM_HOST` or `TAPROOM_PORT` to override the default bind address.
The `visibility` field is descriptive metadata; it does not enforce access.

## Remote deployment

Taproom binds to `127.0.0.1` by default. Its CLI-facing HTTP routes do not
provide built-in authentication. Put a remotely bound instance behind an
authenticated reverse proxy, and set `TAPROOM_SKILL_ROOTS` and
`TAPROOM_MCP_ROOTS` or `TAPROOM_CONFIG` to an explicit allowlist. Never expose
private collection roots through an unauthenticated deployment.

## Use the local CLI

The CLI has no npm dependencies and requires Node.js 20+.

```sh
node bin/taproom.mjs taps
node bin/taproom.mjs search "understand an inherited codebase"
node bin/taproom.mjs search "trace a native process" --tap private
node bin/taproom.mjs info public:skill:skilltap~development~codebase-archeology
node bin/taproom.mjs add public:skill:skilltap~development~codebase-archeology --project .
node bin/taproom.mjs add public:skill:skilltap~development~codebase-archeology --global
```

Capability IDs use `tap:kind:source~path`, so identical skill names from
different taps, sources, or categories remain independently addressable.

## MCP packages

Inspect requirements before fetching or activating a server:

```sh
node bin/taproom.mjs plan public:mcp:mcptap~travel~sandals
node bin/taproom.mjs doctor public:mcp:mcptap~travel~sandals
node bin/taproom.mjs fetch public:mcp:mcptap~travel~sandals --project .
node bin/taproom.mjs configure public:mcp:mcptap~travel~sandals --project . --client codex
```

`plan` reports runtime, transport, launch configuration, required environment,
declared host requirements, detected Python or Node dependencies, lockfiles,
and unresolved setup. `fetch` downloads the complete package and verifies every
file hash without installing system dependencies. `doctor` checks the current
platform, commands, and required environment variables. `configure` prints a
reviewable client configuration; it does not modify client settings.

`add` combines doctor and fetch. It refuses MCP activation when requirements
are incomplete or the local checks fail. An explicit `fetch` remains available
after the operator reviews those warnings.

For dependency-aware activation, an MCP package's `server.json` declares host
requirements alongside its existing runtime, launch, and environment fields:

```json
{
  "requirements": {
    "platforms": ["windows"],
    "commands": [
      {"name": "uv", "version": ">=0.10"}
    ],
    "software": [
      {"name": "x64dbg", "version": "2026.05.27"}
    ],
    "setup": [
      "Copy the matching plugin into the x64dbg or x32dbg plugin directory."
    ]
  }
}
```

Supported platform values are `any`, `linux`, `macos`, and `windows`.
`commands` are checked on `PATH`; `software` and `setup` are presented as
manual verification items. If `requirements` is absent, Taproom reports the
manifest as incomplete and points the operator to the included README and
dependency files.

Project installs go to `<project>/.agents/skills/`. Global installs default to
`~/.agents/skills/`; set `TAPROOM_SKILL_HOME` to target another agent's skill
directory. Existing skills are never replaced unless `--force` is supplied.

## MCP tools

- `list_taps()`
- `search_capabilities(query, kind?, tap?, limit?)`
- `inspect_capability(capability_id)`
- `plan_mcp_server(capability_id)`

Skills are also available through FastMCP's standard skill resources. Search
is implemented over capability metadata because FastMCP's BM25 search transform
indexes tools rather than resources.

## Repository map

- `src/taproom/` contains catalog discovery, ranking, and the FastMCP service.
- `src/taproom/packages.py` builds file manifests and MCP dependency plans.
- `bin/taproom.mjs` is the dependency-free local installer.
- `tests/` covers catalog identity, manifests, search, and CLI installation.
- `assets/` contains the project artwork.

## Test

```sh
uv run python -m unittest discover -s tests
npm test
```

## License

MIT. See [LICENSE](LICENSE).

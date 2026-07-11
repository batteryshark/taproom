#!/usr/bin/env node

import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { access, chmod, mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { delimiter, dirname, join, resolve, sep } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const DEFAULT_SERVER = process.env.TAPROOM_URL ?? "http://127.0.0.1:8768";

function usage() {
  return `Usage:
  taproom taps [--server URL]
  taproom search <query> [--kind skill|mcp] [--tap NAME] [--server URL]
  taproom info <tap:kind:locator> [--server URL]
  taproom plan <tap:mcp:locator> [--server URL]
  taproom doctor <tap:mcp:locator> [--server URL]
  taproom fetch <tap:mcp:locator> (--project [DIR] | --global) [--force]
  taproom configure <tap:mcp:locator> (--project [DIR] | --global) [--client codex|json]
  taproom add <tap:kind:locator> (--project [DIR] | --global) [--server URL] [--force]

Environment:
  TAPROOM_URL        Taproom HTTP origin (default: ${DEFAULT_SERVER})
  TAPROOM_SKILL_HOME Override the global skill directory (default: ~/.agents/skills)
  TAPROOM_MCP_HOME   Override the global MCP package directory (default: ~/.taproom/mcp)`;
}

function parse(argv) {
  const options = { positionals: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (!argument.startsWith("--")) {
      options.positionals.push(argument);
    } else if (["--global", "--force"].includes(argument)) {
      options[argument.slice(2)] = true;
    } else if (argument === "--project") {
      const next = argv[index + 1];
      if (next && !next.startsWith("--")) {
        options.project = next;
        index += 1;
      } else {
        options.project = ".";
      }
    } else {
      const next = argv[++index];
      if (!next) throw new Error(`${argument} requires a value`);
      options[argument.slice(2)] = next;
    }
  }
  return options;
}

function capabilityParts(id) {
  const parts = id.split(":");
  if (parts.length !== 3 || !parts.every(Boolean)) {
    throw new Error("capability ID must be tap:kind:locator");
  }
  return parts;
}

function endpoint(server, path) {
  return new URL(path, server.endsWith("/") ? server : `${server}/`);
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.json();
}

function safeDestination(root, relative) {
  if (!relative || relative.startsWith("/") || relative.split(/[\\/]/).includes("..")) {
    throw new Error(`unsafe skill path: ${relative}`);
  }
  const destination = resolve(root, relative);
  const prefix = resolve(root) + sep;
  if (!destination.startsWith(prefix)) throw new Error(`unsafe skill path: ${relative}`);
  return destination;
}

async function search(options) {
  const query = options.positionals.slice(1).join(" ");
  if (!query) throw new Error("search requires a query");
  const url = endpoint(options.server ?? DEFAULT_SERVER, "/api/v1/search");
  url.searchParams.set("q", query);
  if (options.kind) url.searchParams.set("kind", options.kind);
  if (options.tap) url.searchParams.set("tap", options.tap);
  const payload = await getJson(url);
  for (const item of payload.results) {
    console.log(`${item.id}\n  ${item.description}`);
  }
}

async function taps(options) {
  const payload = await getJson(endpoint(options.server ?? DEFAULT_SERVER, "/api/v1/taps"));
  for (const tap of payload.taps) {
    console.log(`${tap.name} (${tap.visibility}) — ${tap.skills} skills, ${tap.mcp_servers} MCP servers`);
    for (const source of tap.sources) console.log(`  ${source.kind}: ${source.name}`);
  }
}

async function info(options) {
  console.log(JSON.stringify(await getCapability(options), null, 2));
}

async function getCapability(options) {
  const id = options.positionals[1];
  const [tap, kind, locator] = capabilityParts(id ?? "");
  const server = options.server ?? DEFAULT_SERVER;
  const url = endpoint(server, `/api/v1/capabilities/${encodeURIComponent(tap)}/${kind}/${encodeURIComponent(locator)}`);
  return getJson(url);
}

function requireScope(options) {
  if (Boolean(options.project) === Boolean(options.global)) {
    throw new Error("choose exactly one of --project or --global");
  }
}

function installLocation(options, manifest) {
  requireScope(options);
  const { kind, name, tap } = manifest.capability;
  if (kind === "skill") {
    const root = options.global
      ? resolve(process.env.TAPROOM_SKILL_HOME ?? join(homedir(), ".agents", "skills"))
      : resolve(options.project, ".agents", "skills");
    return {
      destination: join(root, name),
      lockPath: options.global ? join(root, ".taproom.lock") : join(resolve(options.project), ".taproom.lock"),
      lockGroup: "skills",
    };
  }
  const root = options.global
    ? resolve(process.env.TAPROOM_MCP_HOME ?? join(homedir(), ".taproom", "mcp"))
    : resolve(options.project, ".taproom", "mcp");
  return {
    destination: join(root, tap, name),
    lockPath: options.global ? join(root, ".taproom.lock") : join(resolve(options.project), ".taproom.lock"),
    lockGroup: "mcp_servers",
  };
}

async function downloadPackage(options, manifest) {
  const id = manifest.capability.id;
  const { tap, kind, locator } = manifest.capability;
  const { destination, lockPath, lockGroup } = installLocation(options, manifest);
  const temporary = `${destination}.taproom-${process.pid}`;

  let destinationExists = false;
  try {
    await stat(destination);
    destinationExists = true;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (destinationExists && !options.force) {
    throw new Error(`${destination} already exists; pass --force to replace it`);
  }

  await rm(temporary, { recursive: true, force: true });
  try {
    for (const file of manifest.files) {
      const target = safeDestination(temporary, file.path);
      const fileUrl = endpoint(options.server ?? DEFAULT_SERVER, `/api/v1/packages/${encodeURIComponent(tap)}/${kind}/${encodeURIComponent(locator)}/files/${file.path.split("/").map(encodeURIComponent).join("/")}`);
      const response = await fetch(fileUrl);
      if (!response.ok) throw new Error(`failed to download ${file.path}: ${response.status}`);
      const bytes = Buffer.from(await response.arrayBuffer());
      const hash = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
      if (hash !== file.hash) throw new Error(`hash mismatch for ${file.path}`);
      await mkdir(dirname(target), { recursive: true });
      await writeFile(target, bytes);
      if (file.executable && process.platform !== "win32") await chmod(target, 0o755);
    }
    await mkdir(dirname(destination), { recursive: true });
    if (options.force) await rm(destination, { recursive: true, force: true });
    await rename(temporary, destination);
  } catch (error) {
    await rm(temporary, { recursive: true, force: true });
    throw error;
  }

  let lock = { version: 1, skills: {}, mcp_servers: {} };
  try { lock = JSON.parse(await readFile(lockPath, "utf8")); } catch (error) { if (error.code !== "ENOENT") throw error; }
  lock[lockGroup] ??= {};
  lock[lockGroup][id] = { installedAt: new Date().toISOString(), path: destination, files: manifest.files.map(({ path, hash }) => ({ path, hash })) };
  await mkdir(dirname(lockPath), { recursive: true });
  await writeFile(lockPath, `${JSON.stringify(lock, null, 2)}\n`);
  console.log(`Installed ${id} to ${destination}`);
  return destination;
}

function printPlan(manifest) {
  if (manifest.capability.kind !== "mcp") throw new Error("plan requires an MCP capability");
  const plan = manifest.plan;
  console.log(`${manifest.capability.id} — ${manifest.capability.description}`);
  console.log(`runtime: ${plan.runtime ?? "not declared"}`);
  console.log(`transport: ${plan.transport ?? "not declared"}`);
  if (plan.launch) console.log(`launch: ${plan.launch.command} ${(plan.launch.args ?? []).join(" ")}`.trim());
  console.log(`requirements: ${plan.requirements_declared ? "declared" : "INCOMPLETE"}`);
  for (const value of plan.detected_dependencies.python) console.log(`  python: ${value}`);
  for (const value of plan.detected_dependencies.node) console.log(`  node: ${value}`);
  for (const item of plan.env.filter((item) => item.required)) console.log(`  required env: ${item.name}`);
  for (const item of plan.unresolved) console.log(`  unresolved: ${item}`);
}

async function commandAvailable(command) {
  if (!command || command.includes("/") || command.includes("\\")) return false;
  const suffixes = process.platform === "win32" ? (process.env.PATHEXT ?? ".EXE;.CMD;.BAT").split(";") : [""];
  for (const directory of (process.env.PATH ?? "").split(delimiter)) {
    for (const suffix of suffixes) {
      try {
        await access(join(directory, `${command}${suffix}`), constants.X_OK);
        return true;
      } catch {}
    }
  }
  return false;
}

async function doctorReport(manifest) {
  if (manifest.capability.kind !== "mcp") throw new Error("doctor requires an MCP capability");
  const { plan } = manifest;
  const blockers = [...plan.unresolved];
  const warnings = [];
  if (plan.runtime) warnings.push(`verify runtime constraint: ${plan.runtime}`);
  const platform = { darwin: "macos", win32: "windows", linux: "linux" }[process.platform] ?? process.platform;
  const platforms = plan.requirements.platforms ?? [];
  if (platforms.length && !platforms.includes("any") && !platforms.includes(platform)) {
    blockers.push(`requires platform ${platforms.join(" or ")}; current platform is ${platform}`);
  }
  const commands = new Set([plan.launch?.command]);
  for (const item of plan.requirements.commands ?? []) {
    commands.add(typeof item === "string" ? item : item.name);
    if (typeof item === "object" && item.version) warnings.push(`verify ${item.name} version ${item.version}`);
  }
  for (const command of commands) {
    if (command && !(await commandAvailable(command))) blockers.push(`command not found on PATH: ${command}`);
  }
  for (const item of plan.env.filter((item) => item.required)) {
    if (!process.env[item.name]) blockers.push(`required environment variable is unset: ${item.name}`);
  }
  for (const item of plan.requirements.software ?? []) {
    warnings.push(`verify external software: ${typeof item === "string" ? item : item.name}`);
  }
  for (const item of plan.requirements.setup ?? []) warnings.push(`manual setup: ${item}`);
  return { blockers, warnings };
}

function printDoctor(report) {
  for (const item of report.blockers) console.log(`BLOCKED: ${item}`);
  for (const item of report.warnings) console.log(`CHECK: ${item}`);
  if (!report.blockers.length) console.log("doctor: ready");
}

async function plan(options) {
  printPlan(await getCapability(options));
}

async function doctor(options) {
  const manifest = await getCapability(options);
  const report = await doctorReport(manifest);
  printDoctor(report);
  if (report.blockers.length) throw new Error("MCP server is not ready on this host");
}

async function fetchMcp(options) {
  const manifest = await getCapability(options);
  if (manifest.capability.kind !== "mcp") throw new Error("fetch requires an MCP capability");
  printPlan(manifest);
  await downloadPackage(options, manifest);
}

async function configure(options) {
  const manifest = await getCapability(options);
  if (manifest.capability.kind !== "mcp") throw new Error("configure requires an MCP capability");
  const { destination } = installLocation(options, manifest);
  try { await stat(destination); } catch { throw new Error(`package is not fetched: ${destination}`); }
  const launch = manifest.plan.launch;
  if (!launch) throw new Error("server has no launch configuration");
  const cwd = resolve(destination, launch.cwd ?? ".");
  if ((options.client ?? "json") === "codex") {
    console.log(`[mcp_servers.${JSON.stringify(manifest.capability.name)}]`);
    console.log(`command = ${JSON.stringify(launch.command)}`);
    console.log(`args = ${JSON.stringify(launch.args ?? [])}`);
    console.log(`cwd = ${JSON.stringify(cwd)}`);
    return;
  }
  if ((options.client ?? "json") !== "json") throw new Error("client must be codex or json");
  console.log(JSON.stringify({ mcpServers: { [manifest.capability.name]: { ...launch, cwd } } }, null, 2));
}

async function add(options) {
  const manifest = await getCapability(options);
  if (manifest.capability.kind === "mcp") {
    printPlan(manifest);
    const report = await doctorReport(manifest);
    printDoctor(report);
    if (report.blockers.length) throw new Error("refusing automatic MCP activation; use fetch after reviewing the plan");
  }
  await downloadPackage(options, manifest);
}

export async function main(argv = process.argv.slice(2)) {
  const options = parse(argv);
  const command = options.positionals[0];
  if (!command || ["help", "--help", "-h"].includes(command)) {
    console.log(usage());
    return;
  }
  if (command === "taps") return taps(options);
  if (command === "search") return search(options);
  if (command === "info") return info(options);
  if (command === "plan") return plan(options);
  if (command === "doctor") return doctor(options);
  if (command === "fetch") return fetchMcp(options);
  if (command === "configure") return configure(options);
  if (command === "add") return add(options);
  throw new Error(`unknown command: ${command}\n\n${usage()}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(`taproom: ${error.message}`);
    process.exitCode = 1;
  });
}

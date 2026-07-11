#!/usr/bin/env node

import { createHash } from "node:crypto";
import { chmod, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, dirname, join, resolve, sep } from "node:path";
import process from "node:process";

const DEFAULT_SERVER = process.env.TAPROOM_URL ?? "http://127.0.0.1:8768";

function usage() {
  return `Usage:
  taproom search <query> [--kind skill|mcp] [--server URL]
  taproom info <source:kind:name> [--server URL]
  taproom add <source:skill:name> (--project [DIR] | --global) [--server URL] [--force]

Environment:
  TAPROOM_URL        Taproom HTTP origin (default: ${DEFAULT_SERVER})
  TAPROOM_SKILL_HOME Override the global skill directory (default: ~/.agents/skills)`;
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
    throw new Error("capability ID must be source:kind:name");
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
  const payload = await getJson(url);
  for (const item of payload.results) {
    console.log(`${item.id}\n  ${item.description}`);
  }
}

async function info(options) {
  const id = options.positionals[1];
  const [source, kind, name] = capabilityParts(id ?? "");
  const url = endpoint(options.server ?? DEFAULT_SERVER, `/api/v1/capabilities/${encodeURIComponent(source)}/${kind}/${encodeURIComponent(name)}`);
  console.log(JSON.stringify(await getJson(url), null, 2));
}

async function add(options) {
  const id = options.positionals[1];
  const [source, kind, name] = capabilityParts(id ?? "");
  if (kind !== "skill") throw new Error("automatic MCP installation is not enabled yet");
  if (Boolean(options.project) === Boolean(options.global)) {
    throw new Error("choose exactly one of --project or --global");
  }
  const skillRoot = options.global
    ? resolve(process.env.TAPROOM_SKILL_HOME ?? join(homedir(), ".agents", "skills"))
    : resolve(options.project, ".agents", "skills");
  const destination = join(skillRoot, name);
  const temporary = `${destination}.taproom-${process.pid}`;
  const server = options.server ?? DEFAULT_SERVER;
  const manifestUrl = endpoint(server, `/api/v1/capabilities/${encodeURIComponent(source)}/skill/${encodeURIComponent(name)}`);
  const manifest = await getJson(manifestUrl);

  try {
    await readFile(join(destination, "SKILL.md"));
    if (!options.force) throw new Error(`${destination} already exists; pass --force to replace it`);
  } catch (error) {
    if (error.code !== "ENOENT" && !String(error.message).includes("already exists")) throw error;
    if (String(error.message).includes("already exists")) throw error;
  }

  await rm(temporary, { recursive: true, force: true });
  try {
    for (const file of manifest.files) {
      const target = safeDestination(temporary, file.path);
      const fileUrl = endpoint(server, `/api/v1/skills/${encodeURIComponent(source)}/${encodeURIComponent(name)}/files/${file.path.split("/").map(encodeURIComponent).join("/")}`);
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

  const lockPath = options.global ? join(skillRoot, ".taproom.lock") : join(resolve(options.project), ".taproom.lock");
  let lock = { version: 1, skills: {} };
  try { lock = JSON.parse(await readFile(lockPath, "utf8")); } catch (error) { if (error.code !== "ENOENT") throw error; }
  lock.skills[id] = { installedAt: new Date().toISOString(), path: destination, files: manifest.files.map(({ path, hash }) => ({ path, hash })) };
  await writeFile(lockPath, `${JSON.stringify(lock, null, 2)}\n`);
  console.log(`Installed ${id} to ${destination}`);
}

export async function main(argv = process.argv.slice(2)) {
  const options = parse(argv);
  const command = options.positionals[0];
  if (!command || ["help", "--help", "-h"].includes(command)) {
    console.log(usage());
    return;
  }
  if (command === "search") return search(options);
  if (command === "info") return info(options);
  if (command === "add") return add(options);
  throw new Error(`unknown command: ${command}\n\n${usage()}`);
}

if (process.argv[1] && basename(process.argv[1]) === basename(import.meta.filename)) {
  main().catch((error) => {
    console.error(`taproom: ${error.message}`);
    process.exitCode = 1;
  });
}

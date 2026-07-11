import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { main } from "../bin/taproom.mjs";

test("help exits without contacting a server", async () => {
  const original = console.log;
  let output = "";
  console.log = (value) => { output += value; };
  try {
    await main(["help"]);
  } finally {
    console.log = original;
  }
  assert.match(output, /taproom search/);
  assert.match(output, /taproom add/);
});

test("taps lists configured registries", async () => {
  const originalFetch = globalThis.fetch;
  const originalLog = console.log;
  const lines = [];
  globalThis.fetch = async () => new Response(JSON.stringify({
    taps: [{
      name: "private",
      visibility: "private",
      skills: 12,
      mcp_servers: 2,
      sources: [
        { name: "skilltap", kind: "skill" },
        { name: "rekit", kind: "mcp" },
      ],
    }],
  }), { status: 200, headers: { "content-type": "application/json" } });
  console.log = (value) => lines.push(value);
  try {
    await main(["taps", "--server", "http://taproom.test"]);
  } finally {
    globalThis.fetch = originalFetch;
    console.log = originalLog;
  }
  assert.match(lines.join("\n"), /private \(private\) — 12 skills, 2 MCP servers/);
  assert.match(lines.join("\n"), /mcp: rekit/);
});

test("add downloads, verifies, and records a project skill", async () => {
  const files = new Map([
    ["SKILL.md", Buffer.from("---\nname: sample\ndescription: Test skill.\n---\n")],
    ["bin/sample", Buffer.from("#!/bin/sh\nprintf sample\\n")],
  ]);
  const manifest = {
    capability: { id: "public:skill:fixture~development~sample", name: "sample" },
    files: [...files].map(([path, bytes]) => ({
      path,
      size: bytes.length,
      hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
      executable: path.startsWith("bin/"),
    })),
  };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = new URL(input);
    if (url.pathname === "/api/v1/capabilities/public/skill/fixture~development~sample") {
      return new Response(JSON.stringify(manifest), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    const prefix = "/api/v1/skills/public/fixture~development~sample/files/";
    const path = decodeURIComponent(url.pathname.slice(prefix.length));
    if (url.pathname.startsWith(prefix) && files.has(path)) {
      return new Response(files.get(path), { status: 200 });
    }
    return new Response("not found", { status: 404 });
  };
  const project = await mkdtemp(join(tmpdir(), "taproom-cli-test-"));
  const original = console.log;
  console.log = () => {};
  try {
    await main([
      "add",
      "public:skill:fixture~development~sample",
      "--project",
      project,
      "--server",
      "http://taproom.test",
    ]);
    assert.equal(
      await readFile(join(project, ".agents", "skills", "sample", "SKILL.md"), "utf8"),
      files.get("SKILL.md").toString(),
    );
    const mode = (await stat(join(project, ".agents", "skills", "sample", "bin", "sample"))).mode;
    if (process.platform !== "win32") assert.ok(mode & 0o100);
    const lock = JSON.parse(await readFile(join(project, ".taproom.lock"), "utf8"));
    assert.equal(lock.skills["public:skill:fixture~development~sample"].files.length, 2);
  } finally {
    console.log = original;
    globalThis.fetch = originalFetch;
    await rm(project, { recursive: true, force: true });
  }
});

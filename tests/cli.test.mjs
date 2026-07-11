import assert from "node:assert/strict";
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


import assert from "node:assert/strict";

const base = process.argv[2] || "http://127.0.0.1:8765";

async function req(path, opts) {
  const r = await fetch(`${base}${path}`, opts);
  assert.ok(r.ok, `${path} -> ${r.status}`);
  return r;
}

const html = await (await req("/")).text();
assert.ok(html.includes("Wiegand Gate Controller"));
await req("/app.css");
await req("/app.js");

const status = await (await req("/api/status")).json();
assert.equal(status.gate.state, "closed");
assert.equal(status.last_unknown.code, "8844112");

await req("/api/action", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ action: "open" }),
});
const st2 = await (await req("/api/status")).json();
assert.equal(st2.gate.state, "open");

await req("/api/users", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ name: "Test Tag", card: "8844112", pin: "", target: "primary", enabled: true }),
});
const users = await (await req("/api/users")).json();
assert.equal(users.users.length, 3);

await req("/api/config", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ sensor: { mode: "dual_limit" } }),
});
const cfg = await (await req("/api/config")).json();
assert.equal(cfg.sensor.mode, "dual_limit");

console.log("Web UI smoke test passed");

import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const sourcePath = new URL("./index.js", import.meta.url);
const source = (await readFile(sourcePath, "utf8"))
  .replace("export default {", "const worker = {") + "\nexport default worker;";
const worker = (await import(`data:text/javascript,${encodeURIComponent(source)}`)).default;

const env = {
  GITHUB_OWNER: "owner",
  GITHUB_REPO: "repo",
  GITHUB_PAT: "test-pat",
  TRIGGER_SHARED_SECRET: "shared-secret",
};

test("rejects manual trigger without the shared secret", async () => {
  let called = false;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { called = true; return new Response(null, { status: 204 }); };
  try {
    const response = await worker.fetch(new Request("https://worker.example/"), env, {});
    assert.equal(response.status, 401);
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects a wrong shared secret", async () => {
  let called = false;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { called = true; return new Response(null, { status: 204 }); };
  try {
    const request = new Request("https://worker.example/", {
      headers: { "X-Worker-Trigger-Secret": "wrong-secret" },
    });
    const response = await worker.fetch(request, env, {});
    assert.equal(response.status, 401);
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("does not reveal missing Worker configuration", async () => {
  const request = new Request("https://worker.example/", {
    headers: { "X-Worker-Trigger-Secret": "shared-secret" },
  });
  const response = await worker.fetch(request, {
    TRIGGER_SHARED_SECRET: "shared-secret",
  }, {});
  assert.equal(response.status, 502);
  assert.equal(await response.text(), "Unable to trigger GitHub Actions");
});

test("dispatches only after authenticating the manual trigger", async () => {
  let called = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    called += 1;
    assert.match(url, /api\.github\.com\/repos\/owner\/repo\/dispatches$/);
    assert.equal(options.headers.Authorization, "Bearer test-pat");
    return new Response(null, { status: 204 });
  };
  try {
    const request = new Request("https://worker.example/", {
      headers: { "X-Worker-Trigger-Secret": "shared-secret" },
    });
    const response = await worker.fetch(request, env, {});
    assert.equal(response.status, 200);
    assert.equal(called, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("does not expose GitHub error details", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("secret response body", { status: 500 });
  try {
    const request = new Request("https://worker.example/", {
      headers: { "X-Worker-Trigger-Secret": "shared-secret" },
    });
    const response = await worker.fetch(request, env, {});
    assert.equal(response.status, 502);
    assert.equal(await response.text(), "Unable to trigger GitHub Actions");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

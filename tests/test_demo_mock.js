"use strict";

const assert = require("assert/strict");
const mock = require("../demo/mock_api.js");


async function main() {
  const scheduledRuntime = mock.createRuntime({
    schedule(callback) {
      assert.equal(this, undefined);
      callback();
    },
  });
  await scheduledRuntime.handle("/api/process", { method: "POST", body: "{}" });
  const scheduledTask = await scheduledRuntime.handle("/api/tasks/current", { method: "GET" });
  assert.equal(scheduledTask.body.task.status, "completed");

  const runtime = mock.createRuntime({ instant: true });
  const initial = await runtime.handle("/api/state", { method: "GET" });
  assert.equal(initial.status, 200);
  assert.equal(initial.body.project.segments.length, 3);

  const media = await runtime.handle("/api/segments/demo-02/thumbnails", { method: "GET" });
  assert.equal(media.body.thumbnails.length, 12);
  assert.ok(media.body.thumbnails.every((frame) => frame.image_url.startsWith("./assets/")));

  await runtime.handle("/api/process", {
    method: "POST",
    body: JSON.stringify({ segment_ids: ["demo-02"] }),
  });
  const completed = await runtime.handle("/api/tasks/current", { method: "GET" });
  assert.equal(completed.body.task.status, "completed");
  assert.equal(completed.body.task.progress, 100);

  await runtime.handle("/api/export", {
    method: "POST",
    body: JSON.stringify({ segment_ids: ["demo-02"] }),
  });
  const exported = await runtime.handle("/api/tasks/current", { method: "GET" });
  assert.equal(exported.body.task.kind, "export");

  const unknown = await runtime.handle("/api/not-allowed", { method: "GET" });
  assert.equal(unknown.status, 404);
  assert.match(unknown.body.error, /静态演示/);

  runtime.reset();
  const reset = await runtime.handle("/api/state", { method: "GET" });
  assert.equal(reset.body.project.segments[1].name, "日出过渡");
}


main().then(() => console.log("Demo mock contracts passed"));

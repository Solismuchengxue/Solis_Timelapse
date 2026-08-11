"use strict";

(function createDemoModule(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.SolisDemoMock = Object.freeze(api);
    if (!root.localStorage.getItem("solis.theme")) root.localStorage.setItem("solis.theme", "light");
    api.install(root);
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", () => api.installDemoChrome(root), { once: true });
    } else {
      api.installDemoChrome(root);
    }
  }
})(globalThis, function demoFactory() {
  const SEGMENT_IDS = ["demo-01", "demo-02", "demo-03"];
  const TASK_STEPS = [0, 35, 72, 100];
  const DOCKER_DOCS_URL = "https://github.com/Solismuchengxue/Solis_Timelapse#docker-部署";
  const LUMINANCE = [0.18, 0.22, 0.28, 0.36, 0.48, 0.60, 0.72, 0.84, 0.80, 0.88, 0.92, 0.95];

  function ok(body, status = 200) {
    return { status, body };
  }

  function rejected(message, status = 409) {
    return ok({ error: message }, status);
  }

  function notFound(message) {
    return ok({ error: message }, 404);
  }

  function idleTask() {
    return { kind: "demo", status: "idle", progress: 0, completed: 0, total: 0, logs: [] };
  }

  function routeSegmentId(path) {
    return decodeURIComponent(path.split("/")[3] || "");
  }

  function parseBody(body) {
    if (!body) return {};
    if (typeof body === "string") {
      try { return JSON.parse(body); } catch (_error) { return {}; }
    }
    return body;
  }

  function mergeObjects(base, updates) {
    const result = { ...base };
    Object.entries(updates || {}).forEach(([key, value]) => {
      result[key] = value && typeof value === "object" && !Array.isArray(value)
        ? mergeObjects(base?.[key] || {}, value)
        : value;
    });
    return result;
  }

  function createFrames() {
    return LUMINANCE.map((luminance, index) => {
      const frameNumber = index + 1;
      const minute = 40 + index * 5;
      const hour = 5 + Math.floor(minute / 60);
      const displayMinute = minute % 60;
      const clock = `${String(hour).padStart(2, "0")}:${String(displayMinute).padStart(2, "0")}`;
      const asset = `./assets/frame-${String(frameNumber).padStart(2, "0")}.png`;
      return {
        index,
        name: `合成帧 ${String(frameNumber).padStart(2, "0")} · ${clock}`,
        stable_id: `synthetic-frame-${String(frameNumber).padStart(2, "0")}`,
        url: asset,
        image_url: asset,
        timestamp: `2026-08-09T${clock}:00`,
        luminance,
        width: 1920,
        height: 1080,
        focal_length: 24,
        aperture: 8,
        shutter: frameNumber < 6 ? 1.6 : 0.25,
        iso: frameNumber < 5 ? 400 : 100,
        exposure_bias: 0,
      };
    });
  }

  function createSegment(id, name, start, end, status = "pending") {
    return {
      id,
      name,
      frame_count: 12,
      source_files: createFrames().map((frame) => frame.stable_id),
      rejected_frames: id === "demo-02" ? ["synthetic-frame-04", "synthetic-frame-09"] : [],
      captured_start: `2026-08-09T${start}:00`,
      captured_end: `2026-08-09T${end}:00`,
      focal_length: 24,
      aperture_min: 8,
      aperture_max: 8,
      shutter_min: 0.25,
      shutter_max: 1.6,
      iso_min: 100,
      iso_max: 400,
      location: "合成湖景 / Synthetic lakeside",
      status,
      render_status: status,
      representative_name: "合成代表帧",
      representative_url: id === "demo-02" ? "./assets/frame-08.png" : "./assets/frame-06.png",
      recipe: {
        name: "natural",
        strength: 82,
        golden_strength: 18,
        deflicker: { enabled: true, window: 15, gain_limit: 2 },
        golden: { start: "05:55", end: "06:25", strength: 18 },
      },
    };
  }

  function createInitialState() {
    const frames = createFrames();
    const chart = {
      labels: frames.map((frame) => frame.name.split(" · ").at(-1)),
      luminance: frames.map((frame) => frame.luminance),
      brightness: frames.map((frame) => frame.luminance),
      exposure: frames.map((frame) => frame.luminance),
      iso: frames.map((frame) => frame.iso),
      shutter: frames.map((frame) => frame.shutter),
      aperture: frames.map((frame) => frame.aperture),
    };
    return {
      project: {
        source_dir: "合成素材 / Synthetic sequence",
        duration_seconds: 2.4,
        segments: [
          createSegment("demo-01", "蓝调黎明", "05:40", "05:55"),
          createSegment("demo-02", "日出过渡", "06:00", "06:20"),
          createSegment("demo-03", "暖光稳定", "06:25", "06:35"),
        ],
        hdr_results: [],
      },
      media: Object.fromEntries(SEGMENT_IDS.map((id) => [id, { frames: createFrames(), chart }])),
      capabilities: { mode: "demo", native_directory_picker: false, directory_browser: false },
      settings: {
        workspace_dir: "演示内存 / Demo memory",
        output_dir: "模拟输出 / Simulated output",
        archive_dir: "模拟归档 / Simulated archive",
        processing: { default_recipe: "natural", render_device: "auto" },
        scan: { gap_seconds: 120 },
        logging: { level: "INFO" },
        preview: { fps: 30, width: 1920 },
        export: { resolution: "4k", codec: "h264", crf: 18 },
      },
      presets: [
        { id: "natural", name: "自然", builtin: true, sat: 1, con: 1, pivot: 118 },
        { id: "clear", name: "清透", builtin: true, sat: 1.06, con: 1.04, pivot: 118 },
        { id: "punchy", name: "鲜明", builtin: true, sat: 1.16, con: 1.1, pivot: 118 },
        { id: "custom", name: "自定义", builtin: true, sat: 1, con: 1, pivot: 118 },
      ],
      history: [],
    };
  }

  function createRuntime({ instant = false, schedule = setTimeout } = {}) {
    let state = createInitialState();
    let task = idleTask();

    function segmentById(segmentId) {
      return state.project.segments.find((segment) => segment.id === segmentId);
    }

    function thumbnailsResponse(path) {
      const media = state.media[routeSegmentId(path)];
      return media ? ok({ thumbnails: media.frames, total: media.frames.length }) : notFound("静态演示分段不存在");
    }

    function chartResponse(path) {
      const media = state.media[routeSegmentId(path)];
      return media ? ok({ chart: media.chart }) : notFound("静态演示分段不存在");
    }

    function completeTask(kind) {
      const ids = task.segment_ids || ["demo-02"];
      ids.forEach((id) => {
        const segment = segmentById(id);
        if (!segment) return;
        if (kind === "/api/process") {
          segment.status = "completed";
          segment.render_status = "completed";
        }
        if (kind === "/api/export") segment.export_artifact = { simulated: true, name: `${segment.name}.mp4` };
        if (kind === "/api/archive") segment.archive_artifact = { simulated: true, name: `${segment.name}-archive` };
      });
    }

    function startTask(route, { instant: completeImmediately, schedule: enqueue }, body) {
      const segmentIds = Array.isArray(body.segment_ids) ? body.segment_ids : body.segment_id ? [body.segment_id] : ["demo-02"];
      const taskKind = route === "/api/process" ? body.from_stage || "analyze" : route.split("/").at(-1);
      task = {
        kind: taskKind,
        status: "running",
        progress: 0,
        completed: 0,
        total: 100,
        segment_ids: segmentIds,
        logs: [`[静态演示] ${taskKind} 已开始`],
      };
      if (completeImmediately) {
        task = { ...task, status: "completed", progress: 100, completed: 100, logs: [...task.logs, `[静态演示] ${taskKind} 已完成`] };
        completeTask(route);
      } else {
        TASK_STEPS.slice(1).forEach((progress, index) => enqueue(() => {
          const completed = progress === 100;
          task = {
            ...task,
            status: completed ? "completed" : "running",
            progress,
            completed: progress,
            logs: completed ? [...task.logs, `[静态演示] ${taskKind} 已完成`] : task.logs,
          };
          if (completed) completeTask(route);
        }, 350 * (index + 1)));
      }
      return ok({ task });
    }

    async function handle(path, init = {}) {
      const method = String(init.method || "GET").toUpperCase();
      const body = parseBody(init.body);
      if (method === "GET" && path === "/api/auth/status") return ok({ enabled: false });
      if (method === "GET" && path === "/api/state") return ok({ project: state.project, task });
      if (method === "GET" && path === "/api/capabilities") return ok(state.capabilities);
      if (method === "GET" && path === "/api/tasks/current") return ok({ task });
      if (method === "GET" && path === "/api/settings") return ok({ settings: state.settings });
      if (method === "PUT" && path === "/api/settings") {
        state.settings = mergeObjects(state.settings, body);
        return ok({ settings: state.settings, restart_required: false });
      }
      if (method === "GET" && path === "/api/color-presets") return ok({ presets: state.presets, default: "natural" });
      if (method === "POST" && path === "/api/pick-directory") return ok({ path: "合成素材 / Synthetic sequence" });
      if (method === "GET" && /^\/api\/segments\/[^/]+\/thumbnails$/.test(path)) return thumbnailsResponse(path);
      if (method === "GET" && /^\/api\/segments\/[^/]+\/chart$/.test(path)) return chartResponse(path);
      if (method === "GET" && /^\/api\/segments\/[^/]+\/frames\/\d+\/exif$/.test(path)) {
        const segmentId = routeSegmentId(path);
        const index = Number(path.split("/")[5]);
        const frame = state.media[segmentId]?.frames[index];
        return frame ? ok({ frame, exif: { Source: "Synthetic demo data", Notice: "No real file metadata" } }) : notFound("静态演示帧不存在");
      }
      if (method === "PATCH" && /^\/api\/segments\/[^/]+$/.test(path)) {
        const segment = segmentById(routeSegmentId(path));
        if (!segment) return notFound("静态演示分段不存在");
        Object.assign(segment, mergeObjects(segment, body));
        return ok({ segment });
      }
      if (method === "POST" && ["/api/project/scan", "/api/process", "/api/export", "/api/archive"].includes(path)) {
        return startTask(path, { instant, schedule }, body);
      }
      if (method === "POST" && path === "/api/tasks/cancel") {
        task = { ...task, status: "cancelled", logs: [...task.logs, "[静态演示] 操作已取消"] };
        return ok({ task });
      }
      if (method === "DELETE" && path === "/api/project") {
        state = createInitialState();
        task = idleTask();
        return ok({ project: null, task });
      }
      if (method === "GET" && path === "/api/history") return ok({ history: state.history });
      if (method === "GET" && path === "/api/logs") return ok({ logs: task.logs });
      if (method === "DELETE" && path === "/api/logs") {
        task = { ...task, logs: [] };
        return ok({ logs: [] });
      }
      if (
        path === "/api/segments/split" || path === "/api/segments/merge" || path === "/api/segments/reorder"
        || path === "/api/hdr" || path === "/api/hdr/results" || path.startsWith("/api/history/")
        || (path === "/api/history" && method === "DELETE")
        || (path.startsWith("/api/color-presets") && method !== "GET")
      ) return rejected("静态演示不执行此操作");
      return notFound("静态演示未提供此操作");
    }

    return {
      handle,
      reset: () => { state = createInitialState(); task = idleTask(); },
    };
  }

  function install(target) {
    const runtime = createRuntime();
    const originalFetch = target.fetch.bind(target);
    target.fetch = async (input, init = {}) => {
      const url = new URL(typeof input === "string" ? input : input.url, target.location.href);
      if (url.origin !== target.location.origin) {
        return new target.Response(JSON.stringify({ error: "静态演示禁止外部请求" }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        });
      }
      const result = await runtime.handle(url.pathname, { ...init, body: init.body });
      return new target.Response(JSON.stringify(result.body), {
        status: result.status,
        headers: { "Content-Type": "application/json" },
      });
    };
    return { runtime, restore: () => { target.fetch = originalFetch; } };
  }

  function installDemoChrome(target) {
    const tools = target.document.querySelector(".header-tools");
    if (!tools || tools.querySelector(".demo-notice")) return;
    const header = tools.closest(".studio-header");
    header?.classList.add("static-demo-header");
    if (!target.document.querySelector("#static-demo-style")) {
      const style = target.document.createElement("style");
      style.id = "static-demo-style";
      style.textContent = `
        @media (max-width: 720px) {
          .studio-header.static-demo-header { display: block; }
          .static-demo-header .header-tools { flex-wrap: wrap; margin-top: 6px; }
          .static-demo-header .demo-notice { display: inline-flex; flex: 1 1 100%; justify-content: center; text-align: center; }
          .static-demo-header .demo-docker-link { margin-right: auto; white-space: nowrap; }
        }
      `;
      target.document.head.append(style);
    }
    const notice = target.document.createElement("span");
    notice.className = "status-pill demo-notice";
    const link = target.document.createElement("a");
    link.className = "demo-docker-link";
    link.href = DOCKER_DOCS_URL;
    link.target = "_blank";
    link.rel = "noreferrer";
    const translate = () => {
      const english = target.localStorage.getItem("solis.language")?.startsWith("en");
      notice.textContent = english
        ? "Static demo · Synthetic data · No real files processed"
        : "静态演示 · 合成数据 · 不处理真实文件";
      link.textContent = english ? "Run the real project with Docker" : "使用 Docker 运行真实项目";
    };
    translate();
    target.addEventListener("solis:languagechange", translate);
    tools.prepend(link);
    tools.prepend(notice);
  }

  return { createRuntime, install, installDemoChrome };
});

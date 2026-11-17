import "./style.css";

type LiveEvent = {
  event_id: string;
  type: string;
  nickname_masked: string;
  gift_name?: string | null;
  combo_count: number;
  price: number;
  text?: string | null;
  ts: number;
};

type Envelope = {
  v: number;
  kind: string;
  seq?: number;
  data: Record<string, unknown>;
};

type Emotion = {
  emotion: string;
  intensity: number;
  priority: number;
  decay_half_life: number;
  is_ducking: boolean;
  phase?: string;
  source_event?: string | null;
};

const TYPE_LABEL: Record<string, string> = {
  danmaku: "弹幕",
  comment: "评论",
  gift: "礼物",
  combo: "连击",
  enter: "进场",
  like: "点赞",
  follow: "关注",
};

const SCENE_TITLE: Record<string, string> = {
  small_gift_combo: "小礼物连击",
  big_gift_rank1: "大礼物榜一",
  danmaku_flood: "弹幕刷屏",
};

const EMOTION_LABEL: Record<string, string> = {
  ambient: "氛围",
  joy: "喜悦",
  hype: "热场",
  awe: "震撼",
  tender: "温柔",
  alert: "警示",
};

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("缺少根节点");

app.innerHTML = `
  <header>
    <div>
      <h1>直播互动演示控制台</h1>
      <p>模拟源 · 暂停只影响事件列表 · 真实采集默认关闭</p>
    </div>
    <div id="conn" class="status off">未连接</div>
  </header>
  <div class="layout">
    <section>
      <div class="panel">
        <h2>模拟回放</h2>
        <div class="row">
          <button id="start" class="primary" type="button">开始回放</button>
          <button id="stop" type="button">停止</button>
          <label class="check"><input id="loop" type="checkbox" /> 循环</label>
        </div>
        <div class="row" style="margin-top:8px">
          <button type="button" data-speed="1">1x</button>
          <button type="button" data-speed="5">5x</button>
          <button type="button" data-speed="20">20x</button>
          <button id="burst" type="button">突发 200 条/秒</button>
        </div>
        <p id="replay" class="muted"></p>
      </div>
      <div class="panel">
        <h2>剧本场景</h2>
        <div id="scenes" class="row"></div>
      </div>
      <div class="panel">
        <h2>合规</h2>
        <label class="check">
          <input id="collect" type="checkbox" />
          真实采集（打开只写审计，不连接平台）
        </label>
        <label class="check">
          <input id="real-source" type="checkbox" />
          真实源 REAL_SOURCE（需再确认一次，仍不连接平台）
        </label>
        <div class="row">
          <button id="start-mock" type="button">启动模拟源</button>
          <button id="health-official" type="button">检查官方桩</button>
          <button id="delete-raw" type="button">删除加密原文</button>
        </div>
        <p id="adapter-note" class="muted"></p>
        <div id="audit" class="audit"></div>
      </div>
    </section>
    <section>
      <div class="panel events">
        <div class="row" style="justify-content:space-between">
          <h2>实时事件</h2>
          <button id="pause" type="button">暂停显示</button>
        </div>
        <div id="backlog" class="paused-note"></div>
        <div id="stream"></div>
      </div>
    </section>
    <section>
      <div class="panel">
        <h2>情绪状态</h2>
        <p id="emotion-name" class="emotion-name">氛围</p>
        <div class="bar"><span id="intensity"></span></div>
        <dl>
          <dt>情绪</dt><dd id="e-name">ambient</dd>
          <dt>强度</dt><dd id="e-int">0</dd>
          <dt>优先级</dt><dd id="e-pri">0</dd>
          <dt>半衰期</dt><dd id="e-decay">-</dd>
          <dt>压低</dt><dd id="e-duck">否</dd>
          <dt>阶段</dt><dd id="e-phase">idle</dd>
        </dl>
      </div>
      <div class="panel">
        <h2>手动气氛 L0–L4</h2>
        <div class="row levels">
          <button type="button" data-level="L0">L0 点赞进场</button>
          <button type="button" data-level="L1">L1 弹幕氛围</button>
          <button type="button" data-level="L2">L2 关注/小礼物</button>
          <button type="button" data-level="L3">L3 中礼物</button>
          <button type="button" data-level="L4">L4 大礼物</button>
        </div>
        <p class="muted">手动挡位只更新情绪并发送特效提示。虚拟打印用下面的按钮单独创建。</p>
      </div>
      <div class="panel">
        <h2>调试台</h2>
        <div class="row">
          <select id="slider-emotion">
            <option value="ambient">氛围</option>
            <option value="joy">喜悦</option>
            <option value="hype">热场</option>
            <option value="awe">震撼</option>
            <option value="tender">温柔</option>
            <option value="alert">警示</option>
          </select>
          <input id="slider-intensity" type="range" min="0" max="100" value="60" />
          <button id="apply-slider" type="button">应用情绪</button>
          <button id="step" type="button">单步点赞</button>
        </div>
        <div class="row">
          <label class="check">时间轴 <input id="seek" type="range" min="0" max="100" value="0" /></label>
          <button id="seek-live" type="button">回到直播</button>
          <label class="check"><input id="mute" type="checkbox" /> 静音</label>
        </div>
        <p id="overlay-stats" class="muted">等待特效页上报帧率</p>
      </div>
      <div class="panel">
        <h2>虚拟打印</h2>
        <div class="row">
          <select id="style">
            <option value="cartoon">卡通</option>
            <option value="hologram">全息</option>
            <option value="realistic">写实</option>
          </select>
          <select id="avatar">
            <option value="stylized">风格化</option>
            <option value="real">真人向</option>
          </select>
          <input id="duration" type="number" min="0.2" max="600" value="45" />
          <button id="print" type="button">创建任务</button>
        </div>
        <div id="jobs" class="muted"></div>
      </div>
    </section>
  </div>
  <section class="panel" style="margin:0 14px 14px">
    <div class="row" style="justify-content:space-between">
      <h2>映射表</h2>
      <div class="row">
        <button id="reload-yaml" type="button">重新读取</button>
        <button id="save-yaml" class="primary" type="button">保存并热加载</button>
      </div>
    </div>
    <textarea id="yaml" spellcheck="false"></textarea>
    <p id="yaml-msg" class="banner"></p>
  </section>
  <p id="metrics" class="metrics"></p>
`;

const conn = must<HTMLDivElement>("conn");
const stream = must<HTMLDivElement>("stream");
const backlogNote = must<HTMLDivElement>("backlog");
const pauseBtn = must<HTMLButtonElement>("pause");
const yamlBox = must<HTMLTextAreaElement>("yaml");
const yamlMsg = must<HTMLParagraphElement>("yaml-msg");

let paused = false;
let visible: LiveEvent[] = [];
let pending: LiveEvent[] = [];
let speed = 1;

function must<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`缺少 #${id}`);
  return node as T;
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  if (options?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  const body = await response.json();
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "请求失败";
    throw new Error(detail);
  }
  return body as T;
}

function renderEvents() {
  stream.replaceChildren();
  const rows = visible.slice(-200);
  for (const event of rows) {
    const row = document.createElement("div");
    row.className = "event";
    const time = document.createElement("span");
    time.className = "muted";
    time.textContent = new Date(event.ts * 1000).toLocaleTimeString("zh-CN", { hour12: false });
    const kind = document.createElement("b");
    kind.textContent = TYPE_LABEL[event.type] ?? event.type;
    const text = document.createElement("span");
    const bits = [event.nickname_masked];
    if (event.text) bits.push(event.text);
    if (event.gift_name) bits.push(event.gift_name);
    if (event.combo_count > 1) bits.push(`×${event.combo_count}`);
    if (event.price) bits.push(`档位分 ${event.price}`);
    text.textContent = bits.join(" · ");
    row.append(time, kind, text);
    stream.append(row);
  }
  stream.scrollTop = stream.scrollHeight;
  backlogNote.textContent = paused ? `显示已暂停，积压 ${pending.length} 条。后台仍在接收。` : "";
}

function upsert(into: LiveEvent[], event: LiveEvent) {
  const index = into.findIndex((item) => item.event_id === event.event_id);
  if (index >= 0) into[index] = event;
  else into.push(event);
}

function onEvent(event: LiveEvent) {
  if (paused) upsert(pending, event);
  else {
    upsert(visible, event);
    if (visible.length > 300) visible = visible.slice(-300);
    renderEvents();
  }
  if (paused) backlogNote.textContent = `显示已暂停，积压 ${pending.length} 条。后台仍在接收。`;
}

function showEmotion(state: Emotion) {
  const label = EMOTION_LABEL[state.emotion] ?? state.emotion;
  must<HTMLParagraphElement>("emotion-name").textContent = label;
  must<HTMLElement>("e-name").textContent = `${state.emotion} / ${label}`;
  must<HTMLElement>("e-int").textContent = Number(state.intensity).toFixed(2);
  must<HTMLElement>("e-pri").textContent = String(state.priority);
  must<HTMLElement>("e-decay").textContent = `${state.decay_half_life}s`;
  must<HTMLElement>("e-duck").textContent = state.is_ducking ? "是，正在压低低优先级" : "否";
  must<HTMLElement>("e-phase").textContent = state.phase ?? "-";
  must<HTMLElement>("intensity").style.width = `${Math.round(state.intensity * 100)}%`;
}

function connect() {
  let lastSeq = 0;
  let backoff = 500;
  let socket: WebSocket | null = null;
  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const since = lastSeq > 0 ? String(lastSeq) : "0";
    socket = new WebSocket(`${proto}://${location.host}/ws?since_seq=${since}`);
    socket.onopen = () => {
      backoff = 500;
      conn.textContent = "已连接";
      conn.className = "status on";
    };
    socket.onmessage = (ev) => {
      const msg = JSON.parse(String(ev.data)) as Envelope;
      if (typeof msg.seq === "number" && msg.seq > lastSeq) lastSeq = msg.seq;
      if (msg.kind === "event") {
        const data = msg.data as { event?: LiveEvent };
        if (data.event) onEvent(data.event);
      } else if (msg.kind === "emotion") {
        showEmotion(msg.data as unknown as Emotion);
      } else if (msg.kind === "print_job" || msg.kind === "print_progress") {
        void refreshJobs();
      } else if (msg.kind === "buffer_gap") {
        conn.textContent = "已连接 · 更早的事件已超出 30 秒缓冲";
      }
    };
    socket.onclose = () => {
      conn.textContent = "重连中";
      conn.className = "status off";
      window.setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, 5000);
    };
  };
  open();
  return socket;
}

async function refreshReplay() {
  const status = await api<{ running: boolean; file: string | null; scene: string | null; speed: number; loop: boolean; emitted: number }>("/api/replay");
  speed = status.speed;
  document.querySelectorAll<HTMLButtonElement>("[data-speed]").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.speed) === speed);
  });
  must<HTMLInputElement>("loop").checked = status.loop;
  const label = status.running ? "播放中" : "已停止";
  const sample = status.scene ? SCENE_TITLE[status.scene] ?? status.scene : status.file ?? "无样本";
  must<HTMLParagraphElement>("replay").textContent = `${label} · ${sample} · ${status.speed}x · 已发送 ${status.emitted}`;
}

async function refreshJobs() {
  const jobs = await api<Array<{ job_id: string; style: string; status: string; progress: number }>>("/api/print-jobs");
  const box = must<HTMLDivElement>("jobs");
  box.replaceChildren();
  for (const job of jobs.slice(0, 6)) {
    const line = document.createElement("div");
    line.textContent = `${job.style} · ${job.status} · ${job.progress.toFixed(0)}% · ${job.job_id.slice(0, 8)}`;
    box.append(line);
  }
}

async function refreshAudit() {
  const rows = await api<Array<{ action: string; detail: { note?: string } }>>("/api/audit?limit=8");
  must<HTMLDivElement>("audit").textContent = rows.length
    ? rows.map((row) => `${row.action} ${row.detail.note ?? ""}`).join("\n")
    : "还没有审计记录。";
}

async function loadYaml() {
  const body = await api<{ yaml: string; error: string | null }>("/api/mappings");
  yamlBox.value = body.yaml;
  if (body.error) setYamlMessage(body.error, false);
}

function setYamlMessage(text: string, ok: boolean) {
  yamlMsg.textContent = text;
  yamlMsg.className = ok ? "banner ok" : "banner bad";
}

async function boot() {
  const compliance = await api<{ collection_enabled: boolean; real_source_active: boolean }>("/api/compliance");
  must<HTMLInputElement>("collect").checked = compliance.collection_enabled;
  must<HTMLInputElement>("real-source").checked = compliance.real_source_active;
  const emotion = await api<Emotion>("/api/emotion");
  showEmotion(emotion);
  const scenes = await api<Array<{ name: string; title: string }>>("/api/scenes");
  const sceneBox = must<HTMLDivElement>("scenes");
  for (const scene of scenes) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = scene.title;
    button.addEventListener("click", () => {
      void api("/api/scenes/start", {
        method: "POST",
        body: JSON.stringify({ name: scene.name, speed, loop: must<HTMLInputElement>("loop").checked }),
      }).then(refreshReplay).catch(showPageError);
    });
    sceneBox.append(button);
  }
  await Promise.all([loadYaml(), refreshReplay(), refreshJobs(), refreshAudit()]);
  connect();
  window.setInterval(() => {
    void api<{ dropped: number; latency_ms: { p50: number | null; p99: number | null } }>("/api/metrics")
      .then((metrics) => {
        const p50 = metrics.latency_ms.p50 == null ? "-" : metrics.latency_ms.p50.toFixed(2);
        const p99 = metrics.latency_ms.p99 == null ? "-" : metrics.latency_ms.p99.toFixed(2);
        must<HTMLParagraphElement>("metrics").textContent = `事件到推送队列 p50 ${p50} ms · p99 ${p99} ms · 丢弃 ${metrics.dropped}`;
      })
      .catch(() => undefined);
  }, 2000);
}

function showPageError(error: unknown) {
  setYamlMessage(error instanceof Error ? error.message : "操作失败", false);
}

must<HTMLButtonElement>("start").addEventListener("click", () => {
  void api("/api/replay/start", {
    method: "POST",
    body: JSON.stringify({ file: "replay.jsonl", speed, loop: must<HTMLInputElement>("loop").checked }),
  }).then(refreshReplay).catch(showPageError);
});

must<HTMLButtonElement>("stop").addEventListener("click", () => {
  void api("/api/replay/stop", { method: "POST" }).then(refreshReplay).catch(showPageError);
});

document.querySelectorAll<HTMLButtonElement>("[data-speed]").forEach((button) => {
  button.addEventListener("click", () => {
    const next = Number(button.dataset.speed);
    void api("/api/replay/speed", { method: "POST", body: JSON.stringify({ speed: next }) })
      .then(refreshReplay)
      .catch(showPageError);
  });
});

must<HTMLButtonElement>("burst").addEventListener("click", () => {
  void api("/api/replay/burst", { method: "POST", body: JSON.stringify({ count: 200, window_sec: 1 }) })
    .then(refreshReplay)
    .catch(showPageError);
});

pauseBtn.addEventListener("click", () => {
  paused = !paused;
  pauseBtn.textContent = paused ? "继续显示" : "暂停显示";
  if (!paused) {
    for (const event of pending) upsert(visible, event);
    pending = [];
    if (visible.length > 300) visible = visible.slice(-300);
    renderEvents();
  } else {
    backlogNote.textContent = "显示已暂停，积压 0 条。后台仍在接收。";
  }
});

document.querySelectorAll<HTMLButtonElement>("[data-level]").forEach((button) => {
  button.addEventListener("click", () => {
    const level = button.dataset.level;
    void api<{ emotion: Emotion }>("/api/trigger", { method: "POST", body: JSON.stringify({ level }) })
      .then((body) => showEmotion(body.emotion))
      .catch(showPageError);
  });
});

must<HTMLButtonElement>("save-yaml").addEventListener("click", () => {
  void fetch("/api/mappings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml: yamlBox.value }),
  })
    .then(async (response) => {
      const body = await response.json();
      if (!response.ok) {
        const detail = typeof body.detail === "string" ? body.detail : "映射表无效，已保留上一份配置";
        setYamlMessage(detail, false);
        return;
      }
      setYamlMessage("已热加载，服务没有重启。", true);
    })
    .catch(showPageError);
});

must<HTMLButtonElement>("reload-yaml").addEventListener("click", () => {
  void loadYaml().then(() => setYamlMessage("已重新读取文件。", true)).catch(showPageError);
});

must<HTMLButtonElement>("print").addEventListener("click", () => {
  const duration = Number(must<HTMLInputElement>("duration").value);
  void api("/api/print-jobs", {
    method: "POST",
    body: JSON.stringify({
      style: must<HTMLSelectElement>("style").value,
      avatar_type: must<HTMLSelectElement>("avatar").value,
      duration_sec: duration,
    }),
  }).then(refreshJobs).catch(showPageError);
});

must<HTMLInputElement>("real-source").addEventListener("change", (ev) => {
  const box = ev.target as HTMLInputElement;
  if (box.checked && !window.confirm("第二次确认：打开真实源只会写审计并允许检查官方桩，不会连接任何平台。确认？")) {
    box.checked = false;
    return;
  }
  void api<{ real_source_active: boolean }>("/api/compliance/real-source", {
    method: "POST",
    body: JSON.stringify({ enabled: box.checked, confirm: box.checked }),
  })
    .then(async (body) => {
      box.checked = body.real_source_active;
      await refreshAudit();
    })
    .catch((error: unknown) => {
      box.checked = !box.checked;
      showPageError(error);
    });
});

must<HTMLButtonElement>("start-mock").addEventListener("click", () => {
  void api("/api/adapters/mock/start", { method: "POST" })
    .then((body) => {
      must<HTMLParagraphElement>("adapter-note").textContent = `模拟源 ${JSON.stringify(body)}`;
    })
    .catch(showPageError);
});

must<HTMLButtonElement>("health-official").addEventListener("click", () => {
  void api<Record<string, unknown>>("/api/adapters/official/health")
    .then((body) => {
      must<HTMLParagraphElement>("adapter-note").textContent = `官方桩 ${String(body.state ?? "")} ${String(body.detail ?? "")}`;
    })
    .catch(showPageError);
});

must<HTMLButtonElement>("delete-raw").addEventListener("click", () => {
  void fetch("/api/raw-payloads", { method: "DELETE" })
    .then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error("删除失败");
      must<HTMLParagraphElement>("adapter-note").textContent = `已删除加密原文 ${String(body.deleted)} 条`;
    })
    .catch(showPageError);
});

must<HTMLInputElement>("collect").addEventListener("change", (ev) => {
  const box = ev.target as HTMLInputElement;
  if (box.checked && !window.confirm("打开真实采集只会写入审计日志，不会连接任何平台。确认？")) {
    box.checked = false;
    return;
  }
  void api("/api/compliance/collection", {
    method: "POST",
    body: JSON.stringify({ enabled: box.checked }),
  }).then(refreshAudit).catch((error: unknown) => {
    box.checked = !box.checked;
    showPageError(error);
  });
});

must<HTMLButtonElement>("apply-slider").addEventListener("click", () => {
  const emotion = must<HTMLSelectElement>("slider-emotion").value;
  const intensity = Number(must<HTMLInputElement>("slider-intensity").value) / 100;
  void api<{ emotion: Emotion }>("/api/debug/emotion", {
    method: "POST",
    body: JSON.stringify({ emotion, intensity }),
  })
    .then((body) => showEmotion(body.emotion))
    .catch(showPageError);
});

must<HTMLButtonElement>("step").addEventListener("click", () => {
  void api("/api/debug/step", { method: "POST" }).catch(showPageError);
});

must<HTMLInputElement>("seek").addEventListener("input", () => {
  const seek = Number(must<HTMLInputElement>("seek").value) / 100;
  void fetch("/api/overlay/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seek }),
  }).catch(() => undefined);
});

must<HTMLButtonElement>("seek-live").addEventListener("click", () => {
  void fetch("/api/overlay/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clear_seek: true }),
  }).catch(() => undefined);
});

must<HTMLInputElement>("mute").addEventListener("change", (ev) => {
  const mute = (ev.target as HTMLInputElement).checked;
  void fetch("/api/overlay/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mute }),
  }).catch(() => undefined);
});

window.setInterval(() => {
  void fetch("/api/overlay/stats")
    .then((response) => response.json())
    .then((stats: { fps?: number; frame_ms?: number; particles?: number; fx?: number; downshifted?: boolean; renderer?: string }) => {
      must<HTMLParagraphElement>("overlay-stats").textContent =
        `FPS ${stats.fps ?? 0} · 帧时间 ${stats.frame_ms ?? 0} ms · 粒子 ${stats.particles ?? 0} · 在场特效 ${stats.fx ?? 0} · ${stats.downshifted ? "已降档" : "满质量"} · ${stats.renderer ?? "none"}`;
    })
    .catch(() => undefined);
}, 1000);

void boot().catch(showPageError);

import "./style.css";
import { createGame, type GameHandle, type FxPerformance } from "./game";
import { applyLoad, stepQuality, type Quality, type QualityConfig } from "./quality";

type Envelope = {
  v: number;
  kind: string;
  seq?: number;
  data: Record<string, unknown>;
};

type OverlayConfig = QualityConfig & {
  width: number;
  height: number;
  transparent: boolean;
  mute: boolean;
  sfx: Record<string, string>;
  performances: Record<string, FxPerformance & { emotion?: string; print?: string | null }>;
  seek: number | null;
  load_level: number;
  preset_only: boolean;
};

const params = new URLSearchParams(location.search);
document.body.classList.toggle("preview", params.has("preview"));
document.body.classList.toggle("hud", params.has("hud"));

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("缺少根节点");
app.innerHTML = `
  <div id="stage">
    <div id="hud">打地鼠</div>
  </div>
`;
const stageNode = document.getElementById("stage");
const hudNode = document.getElementById("hud");
if (!stageNode || !hudNode) throw new Error("舞台未创建");
const stage: HTMLElement = stageNode;
const hud: HTMLElement = hudNode;

const fallbackConfig: OverlayConfig = {
  width: 1920,
  height: 1080,
  transparent: true,
  frame_budget_ms: 12,
  recover_under_ms: 10,
  downshift_after_frames: 8,
  recover_after_frames: 45,
  max_fx: 8,
  max_particles: 20000,
  mute: false,
  sfx: {},
  performances: {},
  seek: null,
  load_level: 0,
  preset_only: false,
};

let config = fallbackConfig;
let quality: Quality = { level: 0, over: 0, under: 0, downshifted: false };
let muted = false;
let emotion = "ambient";
let intensity = 0;

const game: GameHandle | null = createGame(config.width, config.height);
if (game) {
  game.view.className = "layer";
  stage.append(game.view);
  game.onEvent = (cue) => playCue(cue);
}

function fit() {
  const scale = Math.min(window.innerWidth / config.width, window.innerHeight / config.height);
  stage.style.transform = `scale(${scale || 1})`;
}
window.addEventListener("resize", fit);
fit();

async function pullConfig() {
  try {
    const response = await fetch("/api/overlay/config");
    if (!response.ok) return;
    config = { ...fallbackConfig, ...(await response.json()) };
    muted = Boolean(config.mute);
  } catch {
    /* 配置接口不可用时沿用上一份。 */
  }
}

function playCue(name: string) {
  const url = config.sfx[name];
  if (!url || muted) return;
  const audio = new Audio(url);
  audio.play().catch(() => undefined);
}

function performanceFor(fxName: string): FxPerformance {
  const known = config.performances[fxName];
  if (known) return known;
  return fxName === "gift_burst" ? { particles: 48, secondary: false } : { particles: 16, secondary: true };
}

let lastSeq = 0;
let linkDown = false;
function connect() {
  let backoff = 500;
  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const since = lastSeq > 0 ? String(lastSeq) : "0";
    const socket = new WebSocket(`${proto}://${location.host}/ws?since_seq=${since}`);
    socket.onopen = () => {
      linkDown = false;
      backoff = 500;
    };
    socket.onclose = () => {
      linkDown = true;
      (window as Window & { __linkDown?: boolean }).__linkDown = true;
      window.setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, 5000);
    };
    socket.onmessage = (ev) => {
      const msg = JSON.parse(String(ev.data)) as Envelope;
      if (typeof msg.seq === "number" && msg.seq > lastSeq) lastSeq = msg.seq;
      handle(msg);
      backoff = 500;
    };
  };
  open();
}

function handle(msg: Envelope) {
  if (msg.kind === "emotion") {
    emotion = String(msg.data.emotion ?? "ambient");
    intensity = Number(msg.data.intensity ?? 0);
    game?.setMood(emotion, intensity);
    return;
  }

  if (msg.kind === "event") {
    const event = msg.data.event as {
      type?: string;
      text?: string;
      gift_name?: string;
      nickname_masked?: string;
      combo_count?: number;
      avatar_url?: string | null;
    } | undefined;
    if (!event) return;
    const name = event.nickname_masked || "匿名观众";

    if (event.type === "gift" || event.type === "combo") {
      const label = event.gift_name ?? event.text ?? "礼物";
      const count = event.combo_count && event.combo_count > 1 ? ` ×${event.combo_count}` : "";
      game?.spawn(`${label}${count}`, "gift", performanceFor("gift_burst"), quality.level, config.max_particles, config.max_fx, event.avatar_url, name, event.type);
      return;
    }

    const text = event.text ?? "";
    if ((event.type === "danmaku" || event.type === "comment") && text) {
      game?.spawn(text, "danmaku", performanceFor("danmaku_float"), quality.level, config.max_particles, config.max_fx, event.avatar_url, name, event.type);
      return;
    }

    if (event.type === "leave" || event.type === "exit" || event.type === "leave_room") {
      game?.removeViewer(name);
      return;
    }

    if (event.type === "enter" || event.type === "follow" || event.type === "like") {
      game?.spawn(name, "danmaku", performanceFor("danmaku_float"), quality.level, config.max_particles, config.max_fx, event.avatar_url, name, event.type);
    }
    return;
  }

  if (msg.kind === "fx_cue") {
    const name = String(msg.data.fx ?? "");
    const performance = performanceFor(name);
    performance.particles = Number(msg.data.particles ?? performance.particles);
    performance.secondary = Boolean(msg.data.secondary ?? performance.secondary);
    const gift = Boolean(msg.data.print);
    game?.spawn(name, gift ? "gift" : "danmaku", performance, quality.level, config.max_particles, config.max_fx, null, null, "fx_cue");
    playCue(name);
  }
}

let last = performance.now();
let fps = 0;
let workMs = 0;
let frames = 0;
let fpsStamp = performance.now();

function loop(now: number) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  frames += 1;
  const workStart = performance.now();
  const stride = quality.level === 0 ? 1 : quality.level === 1 ? 2 : 3;
  if (frames % stride === 0) game?.tick(dt, quality.level, now, config.max_particles);
  const sample = performance.now() - workStart;
  workMs = workMs * 0.85 + sample * 0.15;
  quality = applyLoad(stepQuality(quality, sample, config), config.load_level);

  if (now - fpsStamp >= 500) {
    fps = Math.round((frames * 1000) / (now - fpsStamp));
    frames = 0;
    fpsStamp = now;
    const heap = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? 0;
    const counts = game?.counts() ?? { particles: 0, fx: 0, wall: 0 };
    const stats = {
      fps,
      frame_ms: Number(workMs.toFixed(2)),
      particles: counts.particles,
      fx: counts.fx,
      wall: counts.wall,
      downshifted: quality.downshifted,
      level: quality.level,
      heap,
      renderer: "canvas2d",
    };
    (window as Window & { __overlayStats?: typeof stats }).__overlayStats = stats;
    hud.textContent = `${stats.fps} fps · 绘制 ${stats.frame_ms} ms · 地鼠特效 ${stats.fx} · 粒子 ${stats.particles}${stats.downshifted ? " · 降档" : ""}`;
    void fetch("/api/overlay/stats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(stats),
    }).catch(() => undefined);
  }
  requestAnimationFrame(loop);
}

void pullConfig();
window.setInterval(() => {
  void pullConfig();
}, 1000);
connect();
requestAnimationFrame(loop);

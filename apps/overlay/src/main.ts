import "./style.css";
import { createScene } from "./scene";
import { createFx, type FxPerformance } from "./fx";
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
    <div id="hud">特效</div>
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
let printProgress = 0;
const scene = createScene(config.width, config.height);
const fx = await createFx(config.width, config.height).catch(() => null);
if (scene) {
  scene.canvas.className = "layer";
  stage.append(scene.canvas);
}
if (fx) {
  fx.view.className = "layer";
  stage.append(fx.view);
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
    if (typeof config.seek === "number" && scene) {
      scene.timeline.progress(config.seek);
      scene.setPrint(config.seek * 100);
    } else if (scene && scene.timeline.paused()) scene.timeline.play();
  } catch {
    /* 配置接口暂时不可用时沿用上一份。 */
  }
}

function playCue(name: string) {
  const url = config.sfx[name];
  if (!url || muted) return;
  const audio = new Audio(url);
  audio.play().catch(() => undefined);
}

function performanceFor(fxName: string): FxPerformance {
  return config.performances[fxName] ?? { particles: 16, secondary: true };
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
      scene?.timeline.play();
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

async function pullAvatar() {
  if (!scene) return;
  try {
    const list = await fetch("/api/avatars").then((response) => response.json());
    const active = (list.assets as Array<{ avatar_id: string; file?: string; glb_rel?: string }> | undefined)?.find(
      (item) => item.avatar_id === list.active,
    );
    const rel = active?.file || active?.glb_rel;
    if (rel) {
      const url = `/avatar-files/${rel}`;
      if (url !== (window as Window & { __avatarUrl?: string }).__avatarUrl) {
        (window as Window & { __avatarUrl?: string }).__avatarUrl = url;
        await scene.showAvatar(url);
      }
    }
    const weights = await fetch(`/api/avatars/blendshapes?emotion=${encodeURIComponent(emotion)}&intensity=${intensity}`).then((response) =>
      response.json(),
    );
    scene.setBlend(weights.weights ?? {});
  } catch {
    /* 角色库还没就绪时继续用场景里的参数化头。 */
  }
}

function handle(msg: Envelope) {
  if (msg.kind === "emotion") {
    emotion = String(msg.data.emotion ?? "ambient");
    intensity = Number(msg.data.intensity ?? 0);
    scene?.setEmotion(emotion, intensity);
  } else if (msg.kind === "event") {
    const event = msg.data.event as { type?: string; text?: string; gift_name?: string; nickname_masked?: string; combo_count?: number } | undefined;
    if (!event) return;
    if ((event.type === "danmaku" || event.type === "comment") && event.text) {
      scene?.setLip(Math.min(1, event.text.length / 12));
      const count = event.combo_count && event.combo_count > 1 ? ` ×${event.combo_count}` : "";
      fx?.spawn(`${event.text}${count}`, "danmaku", performanceFor("danmaku_float"), quality.level, config.max_particles, config.max_fx);
    }
  } else if (msg.kind === "fx_cue") {
    const name = String(msg.data.fx ?? "");
    const performance = performanceFor(name);
    performance.particles = Number(msg.data.particles ?? performance.particles);
    performance.secondary = Boolean(msg.data.secondary ?? performance.secondary);
    fx?.spawn(name, msg.data.print ? "gift" : "danmaku", performance, quality.level, config.max_particles, config.max_fx);
    playCue(name);
    if (scene && scene.timeline.progress() === 0) scene.timeline.play();
  } else if (msg.kind === "print_progress" || msg.kind === "print_job") {
    printProgress = Number(msg.data.progress ?? printProgress);
    printHud = String(msg.data.hud ?? printHud);
    scene?.setPrint(printProgress);
    scene?.setStyle(String(msg.data.style ?? "cartoon"));
  }
}

let printHud = "";
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
  scene?.setQuality(quality.level);
  const stride = quality.level === 0 ? 1 : quality.level === 1 ? 2 : 3;
  if (frames % stride === 0) scene?.tick(now / 1000);
  fx?.tick(dt, quality.level);
  const sample = performance.now() - workStart;
  workMs = workMs * 0.85 + sample * 0.15;
  quality = applyLoad(stepQuality(quality, sample, config), config.load_level);
  if (linkDown && scene) {
    printProgress = (printProgress + dt * (100 / 45)) % 100;
    scene.setPrint(printProgress);
    printHud = "断线保持";
  }
  if (now - fpsStamp >= 500) {
    fps = Math.round((frames * 1000) / (now - fpsStamp));
    frames = 0;
    fpsStamp = now;
    const heap = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? 0;
    const counts = fx?.counts() ?? { particles: 0, fx: 0 };
    const stats = {
      fps,
      frame_ms: Number(workMs.toFixed(2)),
      particles: counts.particles,
      fx: counts.fx,
      downshifted: quality.downshifted,
      level: quality.level,
      heap,
      renderer: scene ? "webgl" : fx ? "pixi" : "none",
    };
    (window as Window & { __overlayStats?: typeof stats }).__overlayStats = stats;
    hud.textContent = `${printHud ? printHud + " · " : ""}${stats.fps} fps · 绘制 ${stats.frame_ms} ms · 粒子 ${stats.particles} · 特效 ${stats.fx}${stats.downshifted ? " · 降档" : ""}`;
    void fetch("/api/overlay/stats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(stats),
    }).catch(() => undefined);
  }
  requestAnimationFrame(loop);
}

void pullConfig();
void pullAvatar();
window.setInterval(() => {
  void pullConfig();
  void pullAvatar();
}, 1000);
connect();
requestAnimationFrame(loop);

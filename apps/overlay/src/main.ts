import "./style.css";

type Envelope = {
  v: number;
  kind: string;
  seq?: number;
  data: Record<string, unknown>;
};

const EMOTION_LABEL: Record<string, string> = {
  ambient: "氛围",
  joy: "喜悦",
  hype: "热场",
  awe: "震撼",
  tender: "温柔",
  alert: "警示",
};

const EMOTION_GLOW: Record<string, string> = {
  ambient: "rgba(126, 182, 255, 0.28)",
  joy: "rgba(240, 162, 2, 0.38)",
  hype: "rgba(255, 122, 69, 0.4)",
  awe: "rgba(188, 154, 255, 0.42)",
  tender: "rgba(255, 158, 181, 0.36)",
  alert: "rgba(225, 90, 74, 0.4)",
};

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("缺少根节点");

app.innerHTML = `
  <div class="stage" id="stage">
    <div class="tag" id="tag">特效预览 · 演示 · 未连接平台</div>
    <div class="orb" id="orb">
      <strong id="name">氛围</strong>
      <span id="meta">强度 0.00</span>
    </div>
    <div class="fx" id="fx"></div>
    <div class="print">
      <div class="track"><span id="bar"></span></div>
      <p id="print-label">还没有虚拟打印任务</p>
    </div>
  </div>
`;

const stage = must("stage");
const orb = must("orb");
const nameEl = must("name");
const metaEl = must("meta");
const fxEl = must("fx");
const bar = must("bar");
const printLabel = must("print-label");
const tag = must("tag");
let printStyle = "";

function must(id: string): HTMLElement {
  const node = document.getElementById(id);
  if (!node) throw new Error(`缺少 #${id}`);
  return node;
}

function fly(text: string) {
  const node = document.createElement("div");
  node.className = "fly";
  node.textContent = text;
  node.style.top = `${8 + Math.random() * 58}%`;
  node.style.animationDuration = `${7 + Math.random() * 4}s`;
  stage.append(node);
  node.addEventListener("animationend", () => node.remove());
  const flying = stage.querySelectorAll(".fly");
  if (flying.length > 40) flying[0]?.remove();
}

function connect() {
  let lastSeq = 0;
  let backoff = 500;
  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const since = lastSeq > 0 ? String(lastSeq) : "0";
    const socket = new WebSocket(`${proto}://${location.host}/ws?since_seq=${since}`);
    socket.onopen = () => {
      backoff = 500;
      tag.textContent = "特效预览 · 已连接 · 未连接平台";
    };
    socket.onclose = () => {
      tag.textContent = "特效预览 · 重连中";
      window.setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, 5000);
    };
    socket.onmessage = (ev) => {
      const msg = JSON.parse(String(ev.data)) as Envelope;
      if (typeof msg.seq === "number" && msg.seq > lastSeq) lastSeq = msg.seq;
      handle(msg);
    };
  };
  open();
}

function handle(msg: Envelope) {
  if (msg.kind === "emotion") {
    const emotion = String(msg.data.emotion ?? "ambient");
    const intensity = Number(msg.data.intensity ?? 0);
    nameEl.textContent = EMOTION_LABEL[emotion] ?? emotion;
    metaEl.textContent = `强度 ${intensity.toFixed(2)} · 优先级 ${String(msg.data.priority ?? 0)} · ${msg.data.is_ducking ? "压低中" : "未压低"}`;
    stage.style.setProperty("--glow", EMOTION_GLOW[emotion] ?? EMOTION_GLOW.ambient);
    orb.style.setProperty("--scale", (0.82 + intensity * 0.35).toFixed(3));
  } else if (msg.kind === "event") {
    const event = msg.data.event as { type?: string; text?: string; gift_name?: string; combo_count?: number; nickname_masked?: string } | undefined;
    if (!event) return;
    if ((event.type === "danmaku" || event.type === "comment") && event.text) {
      const count = event.combo_count && event.combo_count > 1 ? ` ×${event.combo_count}` : "";
      fly(`${event.text}${count}`);
    } else if (event.type === "gift" || event.type === "combo") {
      fxEl.textContent = `${event.nickname_masked ?? ""} ${event.gift_name ?? "礼物"} ×${event.combo_count ?? 1}`;
    }
  } else if (msg.kind === "fx_cue") {
    fxEl.textContent = `${String(msg.data.level ?? "")} · ${String(msg.data.fx ?? "")}`;
  } else if (msg.kind === "print_job" || msg.kind === "print_progress") {
    const progress = Number(msg.data.progress ?? 0);
    const status = String(msg.data.status ?? "");
    if (msg.data.style) printStyle = String(msg.data.style);
    bar.style.width = `${progress}%`;
    printLabel.textContent = `虚拟打印 ${printStyle} ${status} ${progress.toFixed(0)}%`.trim();
  } else if (msg.kind === "buffer_gap") {
    tag.textContent = "特效预览 · 已连接 · 超出 30 秒的事件已过期";
  }
}

connect();

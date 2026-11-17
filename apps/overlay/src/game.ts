/** 弹幕打地鼠小游戏（纯 2D Canvas，无 3D 模型）。
 *
 * 参与方式（弹幕/评论文本）：
 *   #打1 #打2 ... #打9   砸对应洞口的地鼠，打中得 10 分；金鼠 30 分，炸弹扣分。
 *   #左 #右 #中           砸对应列（1/2/3 列）当前露头的地鼠。
 *   送礼/连击：自动给送礼玩家加分并触发一次随机地鼠奖励。
 */
import { admitFx, particleBudget, skipSecondary } from "./quality";

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  max: number;
  size: number;
  color: number;
  kind: "spark" | "glow" | "trail" | "leaf" | "ring";
  spin: number;
};

type Hole = { x: number; y: number; mole: Mole | null };

type Mole = {
  kind: "normal" | "gold" | "bomb";
  bornAt: number;
  life: number;
  hit: boolean;
  hitAt: number;
};

type WallNode = {
  avatarUrl: string | null;
  name: string;
  anchorX: number;
  anchorY: number;
  phase: number;
  life: number;
  img: HTMLImageElement | null;
  loaded: boolean;
};

type Bubble = {
  text: string;
  x: number;
  y: number;
  vx: number;
  life: number;
  max: number;
  gift: boolean;
  name: string;
  roll: boolean;
  combo?: number;
  bornAt?: number;
};

type FloatScore = { x: number; y: number; text: string; life: number; max: number; color: number };

type ComboState = { count: number; best: number };

export type FxCue = "hit" | "gold" | "bomb" | "gift" | "miss";

export type FxPerformance = {
  particles: number;
  secondary: boolean;
  atmosphere_only?: boolean;
};

export type ScoreEntry = { name: string; score: number };

export type GameHandle = {
  view: HTMLCanvasElement;
  resize: (width: number, height: number) => void;
  spawn: (
    text: string,
    kind: "danmaku" | "gift",
    performance: FxPerformance,
    level: number,
    hardCap: number,
    fxCap: number,
    avatar?: string | null,
    nickname?: string | null,
    source?: string,
  ) => void;
  setMood: (emotion: string, intensity: number) => void;
  handleCommand: (text: string, nickname: string | null, kind: string) => boolean;
  removeViewer: (name: string) => void;
  tick: (dt: number, level: number, now: number, hardCap?: number) => void;
  counts: () => { particles: number; fx: number; wall: number };
  scores: () => ScoreEntry[];
  onEvent: ((cue: FxCue) => void) | null;
};

const MOOD_COLOR: Record<string, number> = {
  ambient: 0x8ec8ff,
  joy: 0xf0a202,
  hype: 0xff7a45,
  awe: 0xbc9aff,
  tender: 0xff9eb5,
  alert: 0xe15a4a,
};

const COLS = 3;
const ROWS = 3;
const HOLE_W = 360;
const HOLE_H = 300;
const MOLE_LIFE = 1600;
const GOLD_LIFE = 1300;
const BOMB_LIFE = 1200;

const AVATAR_SIZE = 46;
const WALL_MAX = 14;
const ROUND_LENGTH = 300_000; // 一局时长（毫秒，5 分钟）
const COMBO_STEP = 3; // 每 3 连击提一档倍率
const MAX_MULT = 2; // 倍率封顶

const avatarCache = new Map<string, HTMLImageElement>();

const MOLE_IMG: Record<Mole["kind"], string> = {
  normal: "/overlay/assets/mole_normal.png",
  gold: "/overlay/assets/mole_gold.png",
  bomb: "/overlay/assets/mole_bomb.png",
};
const moleImages: Partial<Record<Mole["kind"], HTMLImageElement>> = {};
for (const [kind, src] of Object.entries(MOLE_IMG)) {
  const img = new Image();
  img.src = src;
  moleImages[kind as Mole["kind"]] = img;
}
const bgImage = new Image();
bgImage.src = "/overlay/assets/bg.webp";

function hex(color: number): string {
  return `#${color.toString(16).padStart(6, "0")}`;
}

function shade(color: number, factor: number): number {
  const r = Math.min(255, Math.max(0, Math.round(((color >> 16) & 0xff) * factor)));
  const g = Math.min(255, Math.max(0, Math.round(((color >> 8) & 0xff) * factor)));
  const b = Math.min(255, Math.max(0, Math.round((color & 0xff) * factor)));
  return (r << 16) | (g << 8) | b;
}

export function createGame(width: number, height: number): GameHandle | null {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return null;
  const ctx: CanvasRenderingContext2D = context;

  const particles: Particle[] = [];
  const wall: WallNode[] = [];
  const scores = new Map<string, number>();
  const bubbles: Bubble[] = [];
  const combos = new Map<string, ComboState>();
  const floats: FloatScore[] = [];

  let mood = "ambient";
  let intensity = 0.3;
  let nextSpawnAt = 0;
  let bgDrift = 0;
  let roundStart = 0;
  let roundEndAt = 0;
  let hits = 0;
  let swings = 0;
  let flash = 0;
  let onEvent: ((cue: FxCue) => void) | null = null;

  const holes: Hole[] = [];
  const gridW = COLS * HOLE_W;
  const gridH = ROWS * HOLE_H;
  const originX = (width - gridW) / 2;
  const originY = (height - gridH) / 2 + 40;
  for (let row = 0; row < ROWS; row += 1) {
    for (let col = 0; col < COLS; col += 1) {
      holes.push({
        x: originX + col * HOLE_W + HOLE_W / 2,
        y: originY + row * HOLE_H + HOLE_H / 2,
        mole: null,
      });
    }
  }

  function moodColor(): number {
    return MOOD_COLOR[mood] ?? MOOD_COLOR.ambient;
  }

  function addScore(name: string, delta: number) {
    const base = scores.get(name) ?? 0;
    scores.set(name, Math.max(0, base + delta));
  }

  // 观众离场：移除其分数、连击与头像墙，榜单由后续名次自动补上。
  function removeViewer(name: string) {
    scores.delete(name);
    combos.delete(name);
    const wi = wall.findIndex((w) => w.name === name);
    if (wi >= 0) wall.splice(wi, 1);
  }

  function comboOf(name: string): ComboState {
    let c = combos.get(name);
    if (!c) {
      c = { count: 0, best: 0 };
      combos.set(name, c);
    }
    return c;
  }

  function comboMult(name: string): number {
    const count = comboOf(name).count;
    const tier = Math.min(MAX_MULT - 1, Math.floor(count / COMBO_STEP));
    return 1 + tier;
  }

  function resetCombo(name: string) {
    const c = combos.get(name);
    if (c) c.count = 0;
  }

  function pushFloat(x: number, y: number, text: string, color: number) {
    floats.push({ x, y, text, life: 1.2, max: 1.2, color });
  }

  function loadAvatar(url: string | null): HTMLImageElement | null {
    if (!url) return null;
    const cached = avatarCache.get(url);
    if (cached) return cached;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => avatarCache.set(url, img);
    img.src = url;
    return null;
  }

  function spawnMole(now: number, progress: number) {
    const empty = holes.filter((h) => !h.mole);
    if (!empty.length) return;
    const hole = empty[Math.floor(Math.random() * empty.length)];
    const roll = Math.random();
    const kind: Mole["kind"] = roll < 0.18 ? "gold" : roll < 0.3 ? "bomb" : "normal";
    const baseLife = kind === "gold" ? GOLD_LIFE : kind === "bomb" ? BOMB_LIFE : MOLE_LIFE;
    // 难度递增：越往后停留越短。
    const life = baseLife * (1 - progress * 0.3);
    hole.mole = { kind, bornAt: now, life, hit: false, hitAt: 0 };
    // 高进度时有概率再冒一只，增加热闹度。
    if (progress > 0.45 && Math.random() < 0.4) {
      const rest = holes.filter((h) => !h.mole);
      if (rest.length) {
        const h2 = rest[Math.floor(Math.random() * rest.length)];
        const r2 = Math.random();
        const k2: Mole["kind"] = r2 < 0.15 ? "gold" : r2 < 0.28 ? "bomb" : "normal";
        const l2 = (k2 === "gold" ? GOLD_LIFE : k2 === "bomb" ? BOMB_LIFE : MOLE_LIFE) * (1 - progress * 0.3);
        h2.mole = { kind: k2, bornAt: now, life: l2, hit: false, hitAt: 0 };
      }
    }
  }

  function burst(x: number, y: number, color: number, count: number, gift = false) {
    for (let i = 0; i < count; i += 1) {
      const angle = Math.random() * Math.PI * 2;
      const speed = (gift ? 160 : 120) + Math.random() * (gift ? 320 : 220);
      particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - (gift ? 120 : 80),
        life: 0.6 + Math.random() * 0.7,
        max: 1.3,
        size: 2 + Math.random() * (gift ? 4 : 3),
        color,
        kind: Math.random() < 0.35 ? "glow" : "spark",
        spin: (Math.random() - 0.5) * 6,
      });
    }
    // 礼物爆发：双色礼花 + 上抛金色光屑 + 环形冲击波。
    if (gift) {
      const confetti = [0xffe08a, 0xff8a3d, 0xff9eb5, 0xfff3c4];
      for (let i = 0; i < Math.floor(count / 2); i += 1) {
        particles.push({
          x: x + (Math.random() - 0.5) * 60,
          y,
          vx: (Math.random() - 0.5) * 60,
          vy: -120 - Math.random() * 160,
          life: 0.9 + Math.random() * 0.8,
          max: 1.7,
          size: 1.5 + Math.random() * 2.5,
          color: confetti[Math.floor(Math.random() * confetti.length)],
          kind: "leaf",
          spin: (Math.random() - 0.5) * 4,
        });
      }
      // 两圈扩散冲击波。
      for (let k = 0; k < 2; k += 1) {
        particles.push({
          x,
          y,
          vx: 120 + k * 60, // 扩张速度（px/s）
          vy: 0,
          life: 0.55 + k * 0.18,
          max: 0.73,
          size: 8 + k * 6, // 初始半径
          color: 0xffd75e,
          kind: "ring",
          spin: 0,
        });
      }
    }
  }

  function heartBurst(x: number, y: number) {
    for (let i = 0; i < 5; i += 1) {
      particles.push({
        x: x + (Math.random() - 0.5) * 30,
        y,
        vx: (Math.random() - 0.5) * 40,
        vy: -60 - Math.random() * 70,
        life: 0.9 + Math.random() * 0.7,
        max: 1.6,
        size: 3 + Math.random() * 3,
        color: 0xff9eb5,
        kind: "leaf",
        spin: (Math.random() - 0.5) * 4,
      });
    }
  }

  function hitHole(hole: Hole, name: string): boolean {
    const mole = hole.mole;
    if (!mole || mole.hit) return false;
    mole.hit = true;
    mole.hitAt = performance.now();
    swings += 1;

    if (mole.kind === "bomb") {
      resetCombo(name);
      addScore(name, -15);
      burst(hole.x, hole.y, 0xe15a4a, 18);
      particles.push({ x: hole.x, y: hole.y, vx: 130, vy: 0, life: 0.5, max: 0.5, size: 10, color: 0xe15a4a, kind: "ring", spin: 0 });
      flash = 1;
      pushFloat(hole.x, hole.y - 40, "-15", 0xe15a4a);
      onEvent?.("bomb");
      return true;
    }

    const base = mole.kind === "gold" ? 30 : 10;
    const mult = comboMult(name);
    const c = comboOf(name);
    c.count += 1;
    c.best = Math.max(c.best, c.count);
    const pts = base * mult;
    addScore(name, pts);
    hits += 1;

    if (mole.kind === "gold") {
      burst(hole.x, hole.y, 0xf0c020, 32, true);
      particles.push({ x: hole.x, y: hole.y, vx: 150, vy: 0, life: 0.55, max: 0.55, size: 12, color: 0xffd75e, kind: "ring", spin: 0 });
      onEvent?.("gold");
    } else {
      burst(hole.x, hole.y, 0x7ec86a, 20);
      particles.push({ x: hole.x, y: hole.y, vx: 110, vy: 0, life: 0.45, max: 0.45, size: 9, color: 0x7ec86a, kind: "ring", spin: 0 });
      onEvent?.("hit");
    }
    pushFloat(
      hole.x,
      hole.y - 40,
      mult > 1 ? `+${pts} ×${mult}` : `+${pts}`,
      mole.kind === "gold" ? 0xf0c020 : 0x7ec86a,
    );
    return true;
  }

  function registerMiss(name: string) {
    resetCombo(name);
    swings += 1;
    onEvent?.("miss");
  }

  function columnHole(col: number): Hole | null {
    const candidates = holes.filter(
      (h) => Math.round((h.x - originX) / HOLE_W) === col && h.mole && !h.mole.hit,
    );
    return candidates.length ? candidates[Math.floor(Math.random() * candidates.length)] : null;
  }

  function handleCommand(text: string, nickname: string | null, kind: string): boolean {
    const name = nickname || "匿名观众";
    const t = text.trim();

    if (kind === "gift") {
      const combo = Number((t.match(/×\s*(\d+)/) ?? [])[1] ?? 1);
      const giftName = t.replace(/×\s*\d+/g, "").trim() || "礼物";
      const mult = 1 + Math.min(4, Math.max(0, combo - 1)) * 0.1;
      addScore(name, Math.round(20 * mult));
      const alive = holes.filter((h) => h.mole && !h.mole.hit);
      if (alive.length) hitHole(alive[Math.floor(Math.random() * alive.length)], name);
      const giftCount = bubbles.filter((b) => b.gift).length;
      const gx = width - 220;
      const gy = 470 + giftCount * 82;
      bubbles.push({
        text: giftName,
        combo,
        x: gx,
        y: gy,
        vx: 0,
        life: 3.2,
        max: 3.2,
        gift: true,
        name,
        roll: false,
        bornAt: 3.2,
      });
      burst(gx, gy, 0xffd75e, 18, true);
      onEvent?.("gift");
      return true;
    }

    // 点名类型：#金鼠 砸金鼠，#普通 砸普通鼠。
    const typeMatch = t.match(/^#?(金鼠|黄金|金|普通|地鼠)$/);
    if (typeMatch) {
      const wantGold = /金/.test(typeMatch[1]);
      const candidates = holes.filter(
        (h) => h.mole && !h.mole.hit && (wantGold ? h.mole!.kind === "gold" : h.mole!.kind === "normal"),
      );
      if (candidates.length) {
        return hitHole(candidates[Math.floor(Math.random() * candidates.length)], name);
      }
      registerMiss(name);
      bubbles.push({ text: wantGold ? "金鼠还没露头" : "这会儿没有普通鼠", x: width / 2, y: 200, vx: 0, life: 1.2, max: 1.2, gift: false, name, roll: false });
      return false;
    }

    const direct = t.match(/^#?打\s*([1-9])$/);
    if (direct) {
      const idx = Number(direct[1]) - 1;
      if (holes[idx] && hitHole(holes[idx], name)) return true;
      registerMiss(name);
      return false;
    }

    const colMap: Record<string, number> = { 左: 0, 右: 2, 中: 1, 1: 0, 2: 1, 3: 2 };
    const colMatch = t.match(/^#?(左|右|中|1|2|3)$/);
    if (colMatch) {
      const hole = columnHole(colMap[colMatch[1]]);
      if (hole && hitHole(hole, name)) return true;
      registerMiss(name);
      return false;
    }
    return false;
  }

  /* ---------- 背景 ---------- */

  function drawBackground(now: number) {
    // 美术背景图铺满，保持比例裁切。
    if (bgImage.complete && bgImage.naturalWidth > 0) {
      const scale = Math.max(width / bgImage.naturalWidth, height / bgImage.naturalHeight);
      const dw = bgImage.naturalWidth * scale;
      const dh = bgImage.naturalHeight * scale;
      ctx.drawImage(bgImage, (width - dw) / 2, (height - dh) / 2, dw, dh);
    } else {
      const base = moodColor();
      const grad = ctx.createLinearGradient(0, 0, 0, height);
      grad.addColorStop(0, `rgba(${(base >> 16) & 0xff},${(base >> 8) & 0xff},${base & 0xff},0.10)`);
      grad.addColorStop(1, "rgba(18,20,28,0.05)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, width, height);
    }

    // 情绪色氛围光晕叠加。
    const base = moodColor();
    bgDrift += 0.0016;
    const glowX1 = width * 0.25 + Math.sin(bgDrift) * 120;
    const glowY1 = height * 0.3;
    const glowX2 = width * 0.75 + Math.cos(bgDrift * 0.8) * 120;
    const glowY2 = height * 0.65;
    for (const [gx, gy, r, a] of [
      [glowX1, glowY1, 420, 0.10],
      [glowX2, glowY2, 380, 0.08],
    ] as const) {
      const rg = ctx.createRadialGradient(gx, gy, 0, gx, gy, r);
      rg.addColorStop(0, `rgba(${(base >> 16) & 0xff},${(base >> 8) & 0xff},${base & 0xff},${a})`);
      rg.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = rg;
      ctx.fillRect(gx - r, gy - r, r * 2, r * 2);
    }
  }

  /* ---------- 地鼠 ---------- */

  function drawHole(hole: Hole, now: number) {
    const mole = hole.mole;

    // 洞口：外圈泥土 + 内圈暗孔，做出坑洞体积感。
    ctx.fillStyle = "rgba(96,66,40,0.95)";
    ctx.beginPath();
    ctx.ellipse(hole.x, hole.y + 30, 104, 26, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(38,26,16,0.95)";
    ctx.beginPath();
    ctx.ellipse(hole.x, hole.y + 30, 88, 18, 0, 0, Math.PI * 2);
    ctx.fill();

    if (!mole) return;
    const elapsed = now - mole.bornAt;
    if (elapsed > mole.life && !mole.hit) {
      hole.mole = null;
      return;
    }
    if (mole.hit && now - mole.hitAt > 500) {
      hole.mole = null;
      return;
    }

    let rise = Math.min(1, elapsed / 180);
    rise = 1 - (1 - rise) * (1 - rise); // easeOut 露头
    if (mole.hit) rise = Math.max(0, 1 - (now - mole.hitAt) / 300);

    const img = moleImages[mole.kind];
    if (img && img.complete && img.naturalWidth > 0) {
      // 精灵图按洞口宽度等比缩放，露头用裁切高度控制。
      const targetW = 150;
      const scale = targetW / img.naturalWidth;
      const targetH = img.naturalHeight * scale;
      // 出生上浮、命中缩回：用可见高度做遮罩。
      const visibleH = targetH * rise;
      const cy = hole.y + 30;
      ctx.save();
      ctx.beginPath();
      ctx.rect(hole.x - targetW / 2, cy - visibleH, targetW, visibleH);
      ctx.clip();
      const wobble = Math.sin(now / 120 + hole.x) * 3;
      ctx.drawImage(img, hole.x - targetW / 2 + wobble, cy - targetH, targetW, targetH);
      ctx.restore();

      // 金鼠头顶星光点缀。
      if (mole.kind === "gold" && !mole.hit) {
        ctx.fillStyle = "rgba(255,247,214,0.9)";
        const tw = 0.6 + Math.sin(now / 100) * 0.4;
        ctx.beginPath();
        ctx.arc(hole.x + 34, cy - targetH + 18, 3 * tw, 0, Math.PI * 2);
        ctx.fill();
      }
      return;
    }

    // 兜底：图片未加载时的几何地鼠。
    const bodyH = 90 * rise;
    const cy = hole.y + 34 - bodyH;
    const bodyColor = mole.kind === "gold" ? 0xf0c020 : mole.kind === "bomb" ? 0x3a3a44 : 0x8a5a34;
    const dark = shade(bodyColor, 0.6);
    const bodyGrad = ctx.createLinearGradient(hole.x, cy - 30, hole.x, cy + 20);
    bodyGrad.addColorStop(0, hex(shade(bodyColor, 1.15)));
    bodyGrad.addColorStop(1, hex(dark));
    ctx.fillStyle = bodyGrad;
    ctx.beginPath();
    ctx.ellipse(hole.x, cy, 46, bodyH / 2 + 18, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.arc(hole.x - 16, cy - 6, 8, 0, Math.PI * 2);
    ctx.arc(hole.x + 16, cy - 6, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#1a1a1a";
    ctx.beginPath();
    ctx.arc(hole.x - 16, cy - 6, 3.5, 0, Math.PI * 2);
    ctx.arc(hole.x + 16, cy - 6, 3.5, 0, Math.PI * 2);
    ctx.fill();
  }

  /* ---------- 气泡 / 榜单 / 头像墙 ---------- */

  function drawBubble(b: Bubble, now: number) {
    const alpha = Math.min(1, b.life / b.max);

    // 礼物卡片：金色渐变底 + 礼盒图标 + 昵称/礼物名两行 + 入场弹入。
    if (b.gift) {
      const p = 1 - b.life / b.max;
      const scale = p < 0.25 ? 0.55 + (p / 0.25) * 0.5 : 1;
      const fy = b.y + Math.sin(now / 320 + b.x) * 3;
      const combo = b.combo ?? 1;
      const nameLine = b.name || "匿名观众";
      const giftLine = combo > 1 ? `${b.text} ×${combo}` : b.text;

      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.translate(b.x, fy);
      ctx.scale(scale, scale);

      ctx.font = "16px 'Microsoft YaHei', sans-serif";
      const nameW = ctx.measureText(nameLine).width;
      ctx.font = "bold 21px 'Microsoft YaHei', sans-serif";
      const giftW = ctx.measureText(giftLine).width;
      const textW = Math.max(nameW, giftW);
      const w = 50 + textW + 32;
      const h = 72;

      const bg = ctx.createLinearGradient(-w / 2, -h / 2, w / 2, h / 2);
      bg.addColorStop(0, "rgba(255,196,60,0.96)");
      bg.addColorStop(1, "rgba(214,110,10,0.96)");
      ctx.shadowColor = "rgba(255,180,60,0.7)";
      ctx.shadowBlur = 16;
      ctx.fillStyle = bg;
      ctx.beginPath();
      ctx.roundRect(-w / 2, -h / 2, w, h, 18);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = "rgba(255,242,208,0.9)";
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // 扫过卡片的斜向高光。
      ctx.save();
      ctx.beginPath();
      ctx.roundRect(-w / 2, -h / 2, w, h, 18);
      ctx.clip();
      const sweep = (now / 1500 + b.x / 500) % 1;
      const sx = -w / 2 + sweep * w;
      const shine = ctx.createLinearGradient(sx - 26, 0, sx + 26, 0);
      shine.addColorStop(0, "rgba(255,255,255,0)");
      shine.addColorStop(0.5, "rgba(255,255,255,0.32)");
      shine.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = shine;
      ctx.translate(sx, 0);
      ctx.rotate(-0.35);
      ctx.fillRect(-26, -h, 52, h * 2);
      ctx.restore();

      // 礼盒图标：红盒身 + 金丝带 + 蝴蝶结。
      const ix = -w / 2 + 28;
      ctx.fillStyle = "#b83a2a";
      ctx.beginPath();
      ctx.roundRect(ix - 16, -9, 32, 24, 5);
      ctx.fill();
      ctx.fillStyle = "#ffe08a";
      ctx.fillRect(ix - 2.5, -9, 5, 24);
      ctx.fillRect(ix - 16, -2, 32, 5);
      ctx.beginPath();
      ctx.arc(ix - 6, -13, 5, 0, Math.PI * 2);
      ctx.arc(ix + 6, -13, 5, 0, Math.PI * 2);
      ctx.fill();

      const tx = ix + 28;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.font = "16px 'Microsoft YaHei', sans-serif";
      ctx.fillStyle = "#fff7ea";
      ctx.fillText(nameLine, tx, -14);
      ctx.font = "bold 21px 'Microsoft YaHei', sans-serif";
      ctx.fillStyle = "#fff2c4";
      ctx.fillText(giftLine, tx, 14);

      // 角落闪烁星芒。
      const tw = (Math.sin(now / 200 + b.x) + 1) / 2;
      ctx.globalAlpha = alpha * (0.3 + 0.7 * tw);
      ctx.fillStyle = "#fff";
      drawStar(w / 2 - 12, -h / 2 + 12, 4);
      const tw2 = (Math.sin(now / 230 + b.x + 2) + 1) / 2;
      ctx.globalAlpha = alpha * (0.25 + 0.6 * tw2);
      drawStar(-w / 2 + 14, h / 2 - 12, 3);

      ctx.restore();
      ctx.globalAlpha = 1;
      return;
    }

    // 普通弹幕气泡。
    ctx.globalAlpha = alpha;
    const label = b.roll && b.name ? `${b.name}：${b.text}` : b.text;
    ctx.font = "bold 20px 'Microsoft YaHei', sans-serif";
    const w = ctx.measureText(label).width + 30;
    const h = 40;
    ctx.fillStyle = "rgba(28,32,42,0.82)";
    ctx.strokeStyle = hex(moodColor());
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(b.x - w / 2, b.y - h / 2, w, h, 14);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#f4f1ea";
    ctx.textAlign = "center";
    ctx.fillText(label, b.x, b.y + 7);
    ctx.globalAlpha = 1;
  }

  function drawHud(now: number) {
    if (!roundEndAt) return;
    const remain = Math.max(0, roundEndAt - now);
    const sec = Math.ceil(remain / 1000);
    const mm = String(Math.floor(sec / 60)).padStart(2, "0");
    const ss = String(sec % 60).padStart(2, "0");
    const total = [...scores.values()].reduce((a, b) => a + b, 0);
    const acc = swings > 0 ? Math.round((hits / swings) * 100) : 100;

    const panelW = 440;
    const panelH = 58;
    const px = (width - panelW) / 2;
    const py = 20;
    ctx.fillStyle = "rgba(18,20,28,0.72)";
    ctx.beginPath();
    ctx.roundRect(px, py, panelW, panelH, 18);
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.10)";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = "bold 22px 'Microsoft YaHei', sans-serif";
    ctx.fillStyle = remain < 10_000 ? "#e15a4a" : "#f4f1ea";
    ctx.fillText(`⏱ ${mm}:${ss}`, px + 90, py + panelH / 2);
    ctx.fillStyle = "#f0c020";
    ctx.fillText(`总分 ${total}`, px + 220, py + panelH / 2);
    ctx.fillStyle = "#d8d4c8";
    ctx.fillText(`命中率 ${acc}%`, px + 350, py + panelH / 2);
    ctx.textBaseline = "alphabetic";
  }

  function drawFloats(dt: number) {
    for (let i = floats.length - 1; i >= 0; i -= 1) {
      const f = floats[i];
      f.life -= dt;
      f.y -= 34 * dt;
      if (f.life <= 0) {
        floats.splice(i, 1);
        continue;
      }
      const alpha = Math.max(0, f.life / f.max);
      const age = f.max - f.life;
      const scale = age < 0.2 ? 1.3 - (age / 0.2) * 0.3 : 1;
      ctx.globalAlpha = alpha;
      ctx.save();
      ctx.translate(f.x, f.y);
      ctx.scale(scale, scale);
      ctx.font = "bold 26px 'Microsoft YaHei', sans-serif";
      ctx.textAlign = "center";
      ctx.lineWidth = 4;
      ctx.strokeStyle = "rgba(18,20,28,0.8)";
      ctx.strokeText(f.text, 0, 0);
      ctx.fillStyle = hex(f.color);
      ctx.fillText(f.text, 0, 0);
      ctx.restore();
      ctx.globalAlpha = 1;
    }
  }

  function drawHelp() {
    const lines: Array<[string, string, string]> = [
      ["#打1~9", "砸对应洞口 +10", "#f0c020"],
      ["#左/#中/#右", "砸当前一列", "#f0c020"],
      ["#金鼠", "抢金鼠 +30", "#ffd75e"],
      ["#普通", "砸普通地鼠", "#f0c020"],
      ["小心炸弹", "踩中 −15", "#e15a4a"],
      ["送礼", "自动加分砸鼠", "#ff9eb5"],
    ];
    const panelW = 300;
    const lineH = 36;
    const headH = 56;
    const panelH = headH + lines.length * lineH + 12;
    const px = 24;
    const py = 120;

    // 玻璃渐变底 + 金边高光，与榜单统一风格。
    const bg = ctx.createLinearGradient(px, py, px, py + panelH);
    bg.addColorStop(0, "rgba(28,32,44,0.86)");
    bg.addColorStop(1, "rgba(14,16,24,0.82)");
    ctx.fillStyle = bg;
    ctx.beginPath();
    ctx.roundRect(px, py, panelW, panelH, 20);
    ctx.fill();
    ctx.strokeStyle = "rgba(240,192,32,0.28)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.strokeStyle = "rgba(255,255,255,0.10)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(px + 1, py + 1, panelW - 2, panelH - 2, 19);
    ctx.stroke();

    // 标题：奖杯点 + 文案 + 装饰线。
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#f0c020";
    ctx.beginPath();
    ctx.arc(px + 26, py + 29, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 22px 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("玩法说明", px + 40, py + 29);
    ctx.strokeStyle = "rgba(240,192,32,0.3)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(px + 124, py + 29);
    ctx.lineTo(px + panelW - 24, py + 29);
    ctx.stroke();

    lines.forEach(([cmd, desc, color], i) => {
      const ry = py + headH + i * lineH;
      if (i > 0) {
        ctx.strokeStyle = "rgba(255,255,255,0.07)";
        ctx.beginPath();
        ctx.moveTo(px + 20, ry - lineH / 2);
        ctx.lineTo(px + panelW - 20, ry - lineH / 2);
        ctx.stroke();
      }
      // 类型色点。
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(px + 26, ry, 4, 0, Math.PI * 2);
      ctx.fill();
      // 命令（金色加粗）与描述分栏对齐。
      ctx.font = "bold 18px 'Microsoft YaHei', sans-serif";
      ctx.fillStyle = color;
      ctx.textAlign = "left";
      ctx.fillText(cmd, px + 38, ry + 1);
      ctx.font = "17px 'Microsoft YaHei', sans-serif";
      ctx.fillStyle = "#d8d4c8";
      ctx.fillText(desc, px + 150, ry + 1);
    });
    ctx.textBaseline = "alphabetic";
  }

  function drawAura(cx: number, cy: number, r: number, rank: number, now: number) {
    const colors = ["255,215,94", "210,216,228", "224,160,106"];
    const c = colors[rank];
    const power = [1, 0.7, 0.55][rank];
    const pulse = 0.5 + 0.5 * Math.sin(now / 350 + rank * 1.3);
    const R = r + 5;

    // 柔和径向光晕（强度按名次递减）。
    const rg = ctx.createRadialGradient(cx, cy, r, cx, cy, R + 8);
    rg.addColorStop(0, `rgba(${c},${(0.28 + 0.22 * pulse) * power})`);
    rg.addColorStop(1, `rgba(${c},0)`);
    ctx.fillStyle = rg;
    ctx.beginPath();
    ctx.arc(cx, cy, R + 8, 0, Math.PI * 2);
    ctx.fill();

    // 呼吸描边环。
    ctx.strokeStyle = `rgba(${c},${(0.5 + 0.4 * pulse) * power})`;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.arc(cx, cy, r + 3, 0, Math.PI * 2);
    ctx.stroke();

    if (rank === 0) {
      // 榜一专属：沿金环旋转的流光，加长加浓的彗星拖尾。
      const ang = now / 380;
      const trail = 8;
      ctx.lineCap = "round";
      for (let t = trail; t >= 0; t -= 1) {
        const frac = t / trail; // 0 = 主弧，1 = 尾端
        const start = ang - frac * Math.PI * 0.95;
        const end = ang + Math.PI * 0.45 - frac * Math.PI * 0.22;
        const alpha = t === 0 ? 0.98 : 0.95 * Math.pow(1 - frac, 0.75);
        const radius = r + 3 + frac * 2.2;
        ctx.strokeStyle = t === 0 ? `rgba(255,252,235,${alpha})` : `rgba(255,236,170,${alpha})`;
        ctx.lineWidth = 3.6 - 1.4 * frac;
        if (t === 0) {
          ctx.shadowColor = "rgba(255,215,94,0.9)";
          ctx.shadowBlur = 8;
        }
        ctx.beginPath();
        ctx.arc(cx, cy, radius, start, end);
        ctx.stroke();
        ctx.shadowBlur = 0;
      }
      ctx.lineCap = "butt";

      // 光环外环绕的小金粒子。
      for (let k = 0; k < 3; k += 1) {
        const a = now / 600 + k * ((Math.PI * 2) / 3);
        const pr = R + 7 + Math.sin(now / 300 + k * 2) * 2;
        const px = cx + Math.cos(a) * pr;
        const py = cy + Math.sin(a) * pr;
        const pa = 0.4 + 0.6 * ((Math.sin(now / 250 + k * 1.7) + 1) / 2);
        ctx.fillStyle = `rgba(255,224,130,${pa})`;
        ctx.beginPath();
        ctx.arc(px, py, 1.8, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  function drawStar(x: number, y: number, r: number) {
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r * 0.28, y - r * 0.28);
    ctx.lineTo(x + r, y);
    ctx.lineTo(x + r * 0.28, y + r * 0.28);
    ctx.lineTo(x, y + r);
    ctx.lineTo(x - r * 0.28, y + r * 0.28);
    ctx.lineTo(x - r, y);
    ctx.lineTo(x - r * 0.28, y - r * 0.28);
    ctx.closePath();
    ctx.fill();
  }

  function drawCrown(cx: number, baseY: number, rank: number, now: number) {
    const bob = Math.sin(now / 280 + rank * 1.2) * 2.2;
    const sway = Math.sin(now / 420 + rank) * 0.07;
    const y = baseY + bob;
    const w = 36;
    const h = 20;
    const palettes = [
      { light: "#fff3c4", main: "#ffd75e", dark: "#b8860b", glow: "255,215,94" },
      { light: "#ffffff", main: "#e6e9ef", dark: "#8a909c", glow: "210,216,228" },
      { light: "#ffd9b0", main: "#e0a06a", dark: "#9a5a2a", glow: "224,160,106" },
    ];
    const p = palettes[rank];

    ctx.save();
    ctx.translate(cx, y);
    ctx.rotate(sway);

    // 背后光晕。
    const rg = ctx.createRadialGradient(0, -h / 2, 2, 0, -h / 2, w * 1.15);
    rg.addColorStop(0, `rgba(${p.glow},0.40)`);
    rg.addColorStop(1, `rgba(${p.glow},0)`);
    ctx.fillStyle = rg;
    ctx.beginPath();
    ctx.arc(0, -h / 2, w * 1.15, 0, Math.PI * 2);
    ctx.fill();

    // 冠体金属渐变 + 投影发光。
    ctx.shadowColor = `rgba(${p.glow},0.8)`;
    ctx.shadowBlur = rank === 0 ? 14 : 8;
    const g = ctx.createLinearGradient(0, -h, 0, 0);
    g.addColorStop(0, p.light);
    g.addColorStop(0.5, p.main);
    g.addColorStop(1, p.dark);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.moveTo(-w / 2, 0);
    ctx.lineTo(-w / 2 + 5, -h);
    ctx.lineTo(-6, -4);
    ctx.lineTo(0, -h - 4);
    ctx.lineTo(6, -4);
    ctx.lineTo(w / 2 - 5, -h);
    ctx.lineTo(w / 2, 0);
    ctx.closePath();
    ctx.fill();
    ctx.shadowBlur = 0;

    // 顶部高光棱线。
    ctx.strokeStyle = "rgba(255,255,255,0.55)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(-w / 2 + 5, -h);
    ctx.lineTo(-6, -4);
    ctx.lineTo(0, -h - 4);
    ctx.lineTo(6, -4);
    ctx.lineTo(w / 2 - 5, -h);
    ctx.stroke();

    // 底部厚度暗边。
    ctx.strokeStyle = "rgba(0,0,0,0.25)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(-w / 2, 0);
    ctx.lineTo(w / 2, 0);
    ctx.stroke();

    // 尖顶宝珠（白心 + 金属反光）。
    const spikes: Array<[number, number]> = [
      [-w / 2 + 5, -h],
      [0, -h - 4],
      [w / 2 - 5, -h],
    ];
    for (const [sx, sy] of spikes) {
      ctx.fillStyle = "#fff";
      ctx.beginPath();
      ctx.arc(sx, sy, 2.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = `rgba(${p.glow},0.9)`;
      ctx.beginPath();
      ctx.arc(sx - 0.5, sy - 0.5, 1, 0, Math.PI * 2);
      ctx.fill();
    }

    // 两侧闪烁星芒。
    const tw = (Math.sin(now / 180 + rank * 2) + 1) / 2;
    ctx.globalAlpha = 0.3 + 0.7 * tw;
    ctx.fillStyle = "#fff";
    drawStar(-w / 2 - 3, -h + 3, 3);
    drawStar(w / 2 + 3, -h + 3, 3);
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  function drawLeaderboard(now: number) {
    const top = [...scores.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
    const panelW = 404;
    const rowH = 60;
    const headH = 100;
    const panelH = headH + top.length * rowH + 12;
    const px = width - panelW - 24;
    const py = 24;

    // 玻璃渐变底。
    const bg = ctx.createLinearGradient(px, py, px, py + panelH);
    bg.addColorStop(0, "rgba(28,32,44,0.86)");
    bg.addColorStop(1, "rgba(14,16,24,0.82)");
    ctx.fillStyle = bg;
    ctx.beginPath();
    ctx.roundRect(px, py, panelW, panelH, 20);
    ctx.fill();
    // 金边 + 顶部高光描边。
    ctx.strokeStyle = "rgba(240,192,32,0.28)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.strokeStyle = "rgba(255,255,255,0.10)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(px + 1, py + 1, panelW - 2, panelH - 2, 19);
    ctx.stroke();

    // 标题：奖杯点 + 文案 + 装饰线。
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#f0c020";
    ctx.beginPath();
    ctx.arc(px + 36, py + 34, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 23px 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("得分榜", px + 52, py + 34);
    ctx.strokeStyle = "rgba(240,192,32,0.3)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(px + 142, py + 34);
    ctx.lineTo(px + panelW - 24, py + 34);
    ctx.stroke();

    const medal = ["#f0c020", "#c8ccd4", "#d08a4a"];
    const medalDark = ["#b8860b", "#8a909c", "#9a5a2a"];

    top.forEach(([name, score], i) => {
      const ry = py + headH + i * rowH;
      const isTop = i < 3;

      if (i > 0) {
        ctx.strokeStyle = "rgba(255,255,255,0.07)";
        ctx.beginPath();
        ctx.moveTo(px + 20, ry - rowH / 2);
        ctx.lineTo(px + panelW - 20, ry - rowH / 2);
        ctx.stroke();
      }

      // 名次奖牌圆。
      const mx = px + 36;
      const mr = 17;
      const mg = ctx.createLinearGradient(mx - mr, ry - mr, mx + mr, ry + mr);
      if (isTop) {
        mg.addColorStop(0, medal[i]);
        mg.addColorStop(1, medalDark[i]);
      } else {
        mg.addColorStop(0, "#5a6172");
        mg.addColorStop(1, "#3a4050");
      }
      ctx.fillStyle = mg;
      ctx.beginPath();
      ctx.arc(mx, ry, mr, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.font = "bold 16px 'Microsoft YaHei', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(`${i + 1}`, mx, ry + 1);

      // 头像大圆（取头像墙里同一观众），无头像用首字兜底。
      const av = wall.find((w) => w.name === name);
      const ax = px + 88;
      const ar = 21;
      ctx.strokeStyle = isTop ? medal[i] : "rgba(255,255,255,0.15)";
      ctx.lineWidth = 2;
      if (av?.img && av.loaded) {
        ctx.save();
        ctx.beginPath();
        ctx.arc(ax, ry, ar, 0, Math.PI * 2);
        ctx.clip();
        ctx.drawImage(av.img, ax - ar, ry - ar, ar * 2, ar * 2);
        ctx.restore();
        ctx.beginPath();
        ctx.arc(ax, ry, ar, 0, Math.PI * 2);
        ctx.stroke();
      } else {
        ctx.fillStyle = "rgba(50,56,70,0.9)";
        ctx.beginPath();
        ctx.arc(ax, ry, ar, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "#f4f1ea";
        ctx.font = "bold 16px 'Microsoft YaHei', sans-serif";
        ctx.textAlign = "center";
        ctx.fillText((name || "?").slice(0, 1), ax, ry + 1);
      }

      // 前三名头像呼吸光环 + 上方 3D 动态皇冠。
      if (i < 3) {
        drawAura(ax, ry, ar, i, now);
        drawCrown(ax, ry - ar - 4, i, now);
      }

      // 昵称。
      ctx.textAlign = "left";
      ctx.font = "19px 'Microsoft YaHei', sans-serif";
      ctx.fillStyle = i === 0 ? "#f4e6b0" : "#d8d4c8";
      const display = name.length > 10 ? `${name.slice(0, 10)}…` : name;
      ctx.fillText(display, px + 126, ry + 1);

      // 分数：第一名金色发光。
      ctx.textAlign = "right";
      if (i === 0) {
        ctx.font = "bold 24px 'Microsoft YaHei', sans-serif";
        ctx.fillStyle = "rgba(240,192,32,0.35)";
        ctx.fillText(`${score}`, px + panelW - 28, ry + 2);
        ctx.fillStyle = "#f0c020";
      } else {
        ctx.font = "bold 20px 'Microsoft YaHei', sans-serif";
        ctx.fillStyle = "#e8e4da";
      }
      ctx.fillText(`${score}`, px + panelW - 28, ry + 1);
    });
    ctx.textBaseline = "alphabetic";
  }

  function drawWallNode(node: WallNode) {
    const fade = Math.min(1, node.life / 2);
    const bob = Math.sin(node.phase) * 5;
    const x = node.anchorX;
    const y = node.anchorY + bob;
    ctx.globalAlpha = fade;

    // 光环底。
    const ring = ctx.createRadialGradient(x, y, AVATAR_SIZE / 3, x, y, AVATAR_SIZE / 2 + 8);
    ring.addColorStop(0, "rgba(255,255,255,0.18)");
    ring.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = ring;
    ctx.beginPath();
    ctx.arc(x, y, AVATAR_SIZE / 2 + 8, 0, Math.PI * 2);
    ctx.fill();

    // 圆形裁切头像。
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, AVATAR_SIZE / 2, 0, Math.PI * 2);
    ctx.clip();
    if (node.img && node.loaded) {
      ctx.drawImage(node.img, x - AVATAR_SIZE / 2, y - AVATAR_SIZE / 2, AVATAR_SIZE, AVATAR_SIZE);
    } else {
      ctx.fillStyle = "rgba(50,56,70,0.95)";
      ctx.fillRect(x - AVATAR_SIZE / 2, y - AVATAR_SIZE / 2, AVATAR_SIZE, AVATAR_SIZE);
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 20px 'Microsoft YaHei', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText((node.name || "?").slice(0, 1), x, y);
      ctx.textBaseline = "alphabetic";
    }
    ctx.restore();

    // 描边。
    ctx.strokeStyle = hex(moodColor());
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, AVATAR_SIZE / 2, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  /* ---------- 主循环 ---------- */

  return {
    view: canvas,
    resize(nextWidth, nextHeight) {
      canvas.width = nextWidth;
      canvas.height = nextHeight;
    },
    setMood(next, value) {
      mood = next;
      intensity = Math.max(0, Math.min(1, value));
    },
    handleCommand,
    removeViewer,
    scores: () => [...scores.entries()].map(([name, score]) => ({ name, score })),
    spawn(text, kind, performance, level, hardCap, fxCap, avatarUrl, nickname, source) {
      // 性能 cue 只触发后台特效，不上头像墙、不弹评论气泡。
      if (source === "fx_cue") {
        void text;
        void kind;
        void performance;
        void level;
        void hardCap;
        void fxCap;
        return;
      }
      const name = nickname || "匿名观众";
      const avatar = avatarUrl ?? null;
      if (avatar || nickname) {
        const existing = wall.find((w) => w.name === name);
        if (existing) {
          existing.life = 14;
          existing.avatarUrl = avatar ?? existing.avatarUrl;
        } else {
          const img = avatar ? loadAvatar(avatar) : null;
          wall.push({
            avatarUrl: avatar,
            name,
            anchorX: 96 + (wall.length % 7) * 76,
            anchorY: 930 - Math.floor(wall.length / 7) * 76,
            phase: Math.random() * Math.PI * 2,
            life: 14,
            img,
            loaded: Boolean(img),
          });
          if (wall.length > WALL_MAX) wall.shift();
        }
      }

      const pushBubble = (b: Omit<Bubble, "vx" | "max"> & { vx?: number }) => {
        if (bubbles.length > 12) bubbles.shift();
        bubbles.push({ vx: b.vx ?? 0, max: b.life, ...b });
      };

      if (kind === "gift") {
        handleCommand(text, name, kind);
        return;
      }

      if (source === "enter" || source === "follow" || source === "like") {
        const node = wall.find((w) => w.name === name);
        const hx = node?.anchorX ?? 120;
        const hy = node?.anchorY ?? 860;
        heartBurst(hx, hy);
        const label = source === "like" ? `${name} 点赞` : source === "follow" ? `${name} 关注` : `${name} 进场`;
        pushBubble({ text: label, x: 150, y: hy - 40, life: 2.2, gift: false, name: "", roll: true, vx: 18 });
        return;
      }

      const acted = handleCommand(text, name, kind);
      if (!acted && text) {
        pushBubble({
          text,
          x: 130,
          y: 430 + Math.random() * 200,
          life: 3,
          gift: false,
          name,
          roll: true,
          vx: 18,
        });
      }
      void performance;
      void level;
      void hardCap;
      void fxCap;
    },
    tick(dt, level, now, hardCapLimit = 2000) {
      // 一局计时：到点自动重开，清空命中统计与连击，累计榜单保留。
      if (!roundEndAt) {
        roundStart = now;
        roundEndAt = now + ROUND_LENGTH;
      }
      if (now >= roundEndAt) {
        roundStart = now;
        roundEndAt = now + ROUND_LENGTH;
        hits = 0;
        swings = 0;
        for (const c of combos.values()) c.count = 0;
      }
      const progress = Math.min(1, Math.max(0, (now - roundStart) / ROUND_LENGTH));

      const interval = (1400 - intensity * 600) * (1 - progress * 0.45);
      if (now >= nextSpawnAt) {
        spawnMole(now, progress);
        nextSpawnAt = now + interval * (0.7 + Math.random() * 0.6);
      }
      flash = Math.max(0, flash - dt * 2);

      ctx.clearRect(0, 0, width, height);
      drawBackground(now);

      // 氛围背景粒子：按情绪强度上浮，数量收敛避免底部发杂。
      const ambient = Math.round(4 * intensity) + 1;
      for (let i = 0; i < ambient; i += 1) {
        particles.push({
          x: Math.random() * width,
          y: height * (0.55 + Math.random() * 0.4),
          vx: (Math.random() - 0.5) * 20,
          vy: -30 - Math.random() * 50,
          life: 3 + Math.random() * 2,
          max: 5,
          size: 1 + Math.random() * 2.5,
          color: moodColor(),
          kind: "trail",
          spin: 0,
        });
      }

      for (const hole of holes) drawHole(hole, now);

      // 粒子更新与绘制。
      const cap = Math.min(Number(hardCapLimit) || 2000, 2000);
      for (let i = particles.length - 1; i >= 0; i -= 1) {
        const p = particles[i];
        p.life -= dt;
        if (p.kind !== "ring") {
          p.x += p.vx * dt;
          p.y += p.vy * dt;
          p.vy += (p.kind === "leaf" ? 30 : 60) * dt;
        }
        if (p.spin) p.spin += p.spin * dt;
        if (p.life <= 0) {
          particles.splice(i, 1);
          continue;
        }
        const fade = Math.max(0, p.life / p.max);

        if (p.kind === "glow") {
          const rg = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.size * 3);
          rg.addColorStop(0, `rgba(${(p.color >> 16) & 0xff},${(p.color >> 8) & 0xff},${p.color & 0xff},${0.5 * fade})`);
          rg.addColorStop(1, "rgba(0,0,0,0)");
          ctx.fillStyle = rg;
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.size * 3, 0, Math.PI * 2);
          ctx.fill();
        }
        if (p.kind === "ring") {
          const radius = p.size + (1 - fade) * p.vx;
          ctx.globalAlpha = fade * 0.8;
          ctx.strokeStyle = hex(p.color);
          ctx.lineWidth = 2.5 * fade + 0.5;
          ctx.beginPath();
          ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
          ctx.stroke();
          ctx.globalAlpha = 1;
          continue;
        }
        ctx.globalAlpha = fade;
        ctx.fillStyle = hex(p.color);
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }
      if (particles.length > cap) particles.splice(0, particles.length - cap);

      // 气泡。
      for (let i = bubbles.length - 1; i >= 0; i -= 1) {
        const b = bubbles[i];
        b.life -= dt;
        if (b.roll) {
          b.x += b.vx * dt;
          b.y -= 12 * dt;
        } else {
          b.y -= 20 * dt;
        }
        if (b.life <= 0) {
          bubbles.splice(i, 1);
          continue;
        }
        drawBubble(b, now);
      }

      for (const node of wall) drawWallNode(node);
      drawLeaderboard(now);
      drawHelp();
      drawFloats(dt);
      drawHud(now);

      // 踩雷红闪覆盖层。
      if (flash > 0) {
        ctx.fillStyle = `rgba(225,90,74,${0.18 * flash})`;
        ctx.fillRect(0, 0, width, height);
      }

      void admitFx;
      void particleBudget;
      void skipSecondary;
    },
    counts: () => ({ particles: particles.length, fx: bubbles.length, wall: wall.length }),
    onEvent: null,
  };
}

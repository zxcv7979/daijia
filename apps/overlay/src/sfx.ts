// 轻量 WebAudio 合成音效。config.sfx 里配了文件路径时由 main.ts 优先播放文件，
// 未配置则回退到这里的合成音色，避免外部素材加载失败导致无声。

let ctx: AudioContext | null = null;
let master: GainNode | null = null;

export function ensureAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const AC =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  if (!ctx) {
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = 0.5;
    master.connect(ctx.destination);
  }
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

interface ToneOpts {
  freq: number;
  freqEnd?: number;
  dur: number;
  type?: OscillatorType;
  vol?: number;
  delay?: number;
  attack?: number;
}

function tone(opts: ToneOpts): void {
  const ac = ensureAudioContext();
  if (!ac || !master) return;
  const t0 = ac.currentTime + (opts.delay ?? 0);
  const osc = ac.createOscillator();
  const g = ac.createGain();
  osc.type = opts.type ?? "sine";
  osc.frequency.setValueAtTime(opts.freq, t0);
  if (opts.freqEnd) {
    osc.frequency.exponentialRampToValueAtTime(Math.max(1, opts.freqEnd), t0 + opts.dur);
  }
  const vol = opts.vol ?? 0.5;
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(vol, t0 + (opts.attack ?? 0.01));
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + opts.dur);
  osc.connect(g);
  g.connect(master);
  osc.start(t0);
  osc.stop(t0 + opts.dur + 0.02);
}

interface NoiseOpts {
  dur: number;
  vol?: number;
  delay?: number;
  freq?: number;
  q?: number;
}

function noise(opts: NoiseOpts): void {
  const ac = ensureAudioContext();
  if (!ac || !master) return;
  const t0 = ac.currentTime + (opts.delay ?? 0);
  const len = Math.max(1, Math.floor(ac.sampleRate * opts.dur));
  const buf = ac.createBuffer(1, len, ac.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i += 1) data[i] = Math.random() * 2 - 1;
  const src = ac.createBufferSource();
  src.buffer = buf;
  const filter = ac.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.value = opts.freq ?? 1000;
  filter.Q.value = opts.q ?? 1;
  const g = ac.createGain();
  g.gain.setValueAtTime(opts.vol ?? 0.3, t0);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + opts.dur);
  src.connect(filter);
  filter.connect(g);
  g.connect(master);
  src.start(t0);
  src.stop(t0 + opts.dur + 0.02);
}

// 各 cue 的合成音色表。
const SCHEMAS: Record<string, () => void> = {
  // 普通地鼠：清脆敲击，快速下落。
  hit: () => {
    tone({ freq: 540, freqEnd: 300, dur: 0.12, type: "triangle", vol: 0.55 });
    tone({ freq: 1200, dur: 0.05, type: "square", vol: 0.1 });
  },
  // 金鼠：上扬铃铛琶音 + 高频泛音。
  gold: () => {
    [880, 1174.7, 1568].forEach((f, i) =>
      tone({ freq: f, dur: 0.18, type: "sine", vol: 0.38, delay: i * 0.06 }),
    );
    tone({ freq: 3136, dur: 0.2, type: "sine", vol: 0.1, delay: 0.12 });
  },
  // 踩雷：低频闷砰 + 噪声。
  bomb: () => {
    tone({ freq: 140, freqEnd: 45, dur: 0.35, type: "sawtooth", vol: 0.5 });
    noise({ dur: 0.25, vol: 0.3, freq: 200 });
  },
  // 礼物：欢快上行琶音。
  gift: () => {
    [523.25, 659.25, 783.99, 1046.5].forEach((f, i) =>
      tone({ freq: f, dur: 0.16, type: "triangle", vol: 0.38, delay: i * 0.05 }),
    );
  },
  // 打空：轻柔空挥扫频。
  miss: () => {
    tone({ freq: 320, freqEnd: 150, dur: 0.14, type: "sine", vol: 0.2 });
    noise({ dur: 0.08, vol: 0.08, freq: 900 });
  },
  // 进场：轻快双音。
  enter: () => {
    tone({ freq: 660, dur: 0.08, type: "triangle", vol: 0.3 });
    tone({ freq: 880, dur: 0.1, type: "triangle", vol: 0.3, delay: 0.07 });
  },
  // 关注：上扬确认音。
  follow: () => {
    tone({ freq: 700, freqEnd: 980, dur: 0.18, type: "triangle", vol: 0.32 });
  },
  // 点赞：极短轻叮。
  like: () => {
    tone({ freq: 1000, dur: 0.07, type: "sine", vol: 0.25 });
  },
  // 弹幕：轻柔气泡滑音。
  danmaku: () => {
    tone({ freq: 440, freqEnd: 660, dur: 0.1, type: "sine", vol: 0.18 });
  },
};

export function playSfx(name: string): void {
  const schema = SCHEMAS[name];
  if (!schema) return;
  schema();
}

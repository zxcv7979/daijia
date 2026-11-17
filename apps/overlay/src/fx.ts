import { Application, Container, Graphics, Text } from "pixi.js";
import { admitFx, particleBudget, skipSecondary } from "./quality";

type Particle = { node: Graphics; x: number; y: number; vx: number; vy: number; life: number; max: number };
type Bubble = { node: Container; life: number };

export type FxPerformance = {
  particles: number;
  secondary: boolean;
  atmosphere_only?: boolean;
};

export type FxHandle = {
  view: HTMLCanvasElement;
  resize: (width: number, height: number) => void;
  spawn: (text: string, kind: "danmaku" | "gift", performance: FxPerformance, level: number, hardCap: number, fxCap: number) => void;
  tick: (dt: number, level: number) => void;
  counts: () => { particles: number; fx: number };
};

export async function createFx(width: number, height: number): Promise<FxHandle | null> {
  const app = new Application();
  try {
    await app.init({
      width,
      height,
      backgroundAlpha: 0,
      antialias: false,
      preference: "webgl",
    });
  } catch {
    return null;
  }
  const layer = new Container();
  app.stage.addChild(layer);
  const particles: Particle[] = [];
  const bubbles: Bubble[] = [];

  function cullTo(maxParticles: number) {
    while (particles.length > maxParticles) {
      const doomed = particles.shift();
      doomed?.node.destroy();
    }
  }

  return {
    view: app.canvas,
    resize(nextWidth, nextHeight) {
      app.renderer.resize(nextWidth, nextHeight);
    },
    spawn(text, kind, performance, level, hardCap, fxCap) {
      if (skipSecondary(level, performance.secondary) && kind === "danmaku") return;
      if (!admitFx(bubbles.length, fxCap)) {
        const oldest = bubbles.shift();
        oldest?.node.destroy();
      }
      const bubble = new Container();
      const plate = new Graphics();
      const color = kind === "gift" ? 0xf0a202 : 0xffffff;
      plate.roundRect(0, 0, Math.min(420, 28 + text.length * 18), 42, 16).fill({ color, alpha: kind === "gift" ? 0.9 : 0.2 });
      const label = new Text({
        text,
        style: { fill: kind === "gift" ? 0x1a1200 : 0xf4f1ea, fontSize: 22, fontFamily: "Microsoft YaHei, sans-serif" },
      });
      label.position.set(12, 8);
      bubble.addChild(plate, label);
      bubble.position.set(width + 20, 80 + Math.random() * (height * 0.45));
      layer.addChild(bubble);
      bubbles.push({ node: bubble, life: kind === "gift" ? 2.4 : 6 });

      const requested = particleBudget(level, performance.particles, hardCap);
      const room = Math.max(0, Math.min(hardCap, 2000) - particles.length);
      const count = Math.min(requested, room);
      for (let index = 0; index < count; index += 1) {
        const dot = new Graphics();
        dot.circle(0, 0, kind === "gift" ? 4 : 2).fill({ color, alpha: 0.9 });
        dot.position.set(width * 0.5, height * 0.55);
        layer.addChild(dot);
        particles.push({
          node: dot,
          x: width * 0.5,
          y: height * 0.55,
          vx: (Math.random() - 0.5) * 280,
          vy: -40 - Math.random() * 220,
          life: 0.8 + Math.random() * 0.7,
          max: 1.5,
        });
      }
      cullTo(Math.min(hardCap, 2000));
    },
    tick(dt) {
      for (let index = particles.length - 1; index >= 0; index -= 1) {
        const item = particles[index];
        if (!item) continue;
        item.life -= dt;
        item.x += item.vx * dt;
        item.y += item.vy * dt;
        item.vy += 40 * dt;
        item.node.position.set(item.x, item.y);
        item.node.alpha = Math.max(0, item.life / item.max);
        if (item.life <= 0) {
          item.node.destroy();
          particles.splice(index, 1);
        }
      }
      for (let index = bubbles.length - 1; index >= 0; index -= 1) {
        const item = bubbles[index];
        if (!item) continue;
        item.life -= dt;
        item.node.x -= 140 * dt;
        if (item.life <= 0 || item.node.x < -500) {
          item.node.destroy({ children: true });
          bubbles.splice(index, 1);
        }
      }
    },
    counts: () => ({ particles: particles.length, fx: bubbles.length }),
  };
}

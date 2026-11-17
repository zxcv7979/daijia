/** 与 src/overlay/quality.py 同一套阈值，数字来自 /api/overlay/config。 */

export type Quality = {
  level: number;
  over: number;
  under: number;
  downshifted: boolean;
};

export type QualityConfig = {
  frame_budget_ms: number;
  recover_under_ms: number;
  downshift_after_frames: number;
  recover_after_frames: number;
  max_fx: number;
  max_particles: number;
};

export function stepQuality(state: Quality, frameMs: number, cfg: QualityConfig): Quality {
  let { level, over, under } = state;
  if (frameMs > cfg.frame_budget_ms) {
    over += 1;
    under = 0;
    if (over >= cfg.downshift_after_frames && level < 2) {
      level += 1;
      over = 0;
    }
  } else if (frameMs < cfg.recover_under_ms) {
    under += 1;
    over = 0;
    if (under >= cfg.recover_after_frames && level > 0) {
      level -= 1;
      under = 0;
    }
  } else {
    over = 0;
    under = 0;
  }
  return { level, over, under, downshifted: level > 0 };
}

export function particleBudget(level: number, requested: number, hardCap: number): number {
  const scale = [1, 0.5, 0.25][Math.max(0, Math.min(2, level))] ?? 1;
  return Math.max(0, Math.min(hardCap, Math.floor(requested * scale)));
}

export function admitFx(active: number, cap: number): boolean {
  return active < cap;
}

export function skipSecondary(level: number, secondary: boolean): boolean {
  return secondary && level >= 1;
}

export function applyLoad(state: Quality, loadLevel: number): Quality {
  const level = Math.max(state.level, Math.max(0, Math.min(2, loadLevel)));
  return { ...state, level, downshifted: level > 0 };
}

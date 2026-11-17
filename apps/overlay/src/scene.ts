import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import gsap from "gsap";

export type ShowRig = {
  camZ: number;
  sway: number;
  print: number;
};

export type SceneHandle = {
  canvas: HTMLCanvasElement;
  rig: ShowRig;
  timeline: gsap.core.Timeline;
  setEmotion: (emotion: string, intensity: number) => void;
  setBlend: (weights: Record<string, number>) => void;
  setLip: (amount: number) => void;
  showAvatar: (url: string) => Promise<{ ok: boolean; loadMs: number; kept: boolean }>;
  setPrint: (progress: number) => void;
  setQuality: (level: number) => void;
  tick: (time: number) => void;
  resize: (width: number, height: number) => void;
};

const EMOTION_COLOR: Record<string, number> = {
  ambient: 0x8ec8ff,
  joy: 0xf0a202,
  hype: 0xff7a45,
  awe: 0xbc9aff,
  tender: 0xff9eb5,
  alert: 0xe15a4a,
};

export function createScene(width: number, height: number): SceneHandle | null {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: "high-performance" });
    renderer.setClearColor(0x000000, 0);
    renderer.setSize(width, height, false);
  } catch {
    return null;
  }

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, width / height, 0.1, 40);
  camera.position.set(0, 0.2, 4.4);

  scene.add(new THREE.AmbientLight(0xffffff, 0.65));
  const key = new THREE.DirectionalLight(0xfff2dd, 1.3);
  key.position.set(2, 3, 4);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x88aaff, 0.6);
  rim.position.set(-3, 1, -2);
  scene.add(rim);

  const avatar = new THREE.Group();
  const skin = new THREE.MeshStandardMaterial({ color: 0xf0c8a0, roughness: 0.55, metalness: 0.02 });
  const headGeo = new THREE.SphereGeometry(0.72, 16, 12);
  const jaw = headGeo.attributes.position.clone();
  for (let index = 0; index < jaw.count; index += 1) {
    const y = jaw.getY(index);
    if (y < -0.05) jaw.setY(index, y - 0.18);
  }
  headGeo.morphAttributes.position = [jaw];
  const head = new THREE.Mesh(headGeo, skin);
  head.morphTargetInfluences = [0];
  avatar.add(head);

  const eyeMat = new THREE.MeshStandardMaterial({ color: 0x1b1d26, roughness: 0.3 });
  const leftEye = new THREE.Mesh(new THREE.SphereGeometry(0.08, 10, 8), eyeMat);
  const rightEye = leftEye.clone();
  leftEye.position.set(-0.24, 0.12, 0.62);
  rightEye.position.set(0.24, 0.12, 0.62);
  avatar.add(leftEye, rightEye);

  const brow = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.03, 0.02), new THREE.MeshStandardMaterial({ color: 0x5a4636 }));
  const browR = brow.clone();
  brow.position.set(-0.24, 0.28, 0.66);
  browR.position.set(0.24, 0.28, 0.66);
  avatar.add(brow, browR);

  const body = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.55, 0.7, 3, 8),
    new THREE.MeshStandardMaterial({ color: 0x243044, roughness: 0.7 }),
  );
  body.position.y = -1.15;
  avatar.add(body);
  scene.add(avatar);

  const printMat = new THREE.MeshStandardMaterial({
    color: 0xf0a202,
    transparent: true,
    opacity: 0.85,
    emissive: 0x5a3a00,
  });
  const printBlock = new THREE.Mesh(new THREE.BoxGeometry(0.7, 1, 0.7), printMat);
  printBlock.position.set(1.35, -0.9, 0);
  printBlock.scale.y = 0.04;
  scene.add(printBlock);
  const pedestal = new THREE.Mesh(
    new THREE.BoxGeometry(1, 0.08, 1),
    new THREE.MeshStandardMaterial({ color: 0x888888, wireframe: true }),
  );
  pedestal.position.set(1.35, -1.45, 0);
  scene.add(pedestal);

  const rig: ShowRig = { camZ: 4.4, sway: 0.08, print: 0 };
  const timeline = gsap.timeline({ paused: true });
  timeline
    .to(rig, { camZ: 3.5, duration: 2, ease: "sine.inOut" }, 0)
    .to(rig, { sway: 0.2, duration: 2 }, 0)
    .to(rig, { print: 1, duration: 3, ease: "power1.in" }, 2)
    .to(rig, { camZ: 4.4, sway: 0.08, duration: 2 }, 5);

  let emotion = "ambient";
  let intensity = 0;
  let printProgress = 0;
  let qualityLevel = 0;
  let pixelScale = 1;
  let lip = 0;
  let blend: Record<string, number> = {};
  let shown: THREE.Object3D = avatar;
  const cache = new Map<string, Promise<THREE.Group>>();
  let switchToken = 0;

  function opacityOf(root: THREE.Object3D, value: number) {
    root.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (!mesh.isMesh) return;
      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const material of materials) {
        material.transparent = true;
        material.opacity = value;
      }
    });
  }

  function applyBlend(root: THREE.Object3D, blink: number) {
    root.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (!mesh.isMesh || !mesh.morphTargetDictionary || !mesh.morphTargetInfluences) return;
      for (const [name, value] of Object.entries(blend)) {
        const index = mesh.morphTargetDictionary[name];
        if (index !== undefined) mesh.morphTargetInfluences[index] = value;
      }
      const left = mesh.morphTargetDictionary.eyeBlinkLeft;
      const right = mesh.morphTargetDictionary.eyeBlinkRight;
      const jaw = mesh.morphTargetDictionary.jawOpen;
      if (left !== undefined) mesh.morphTargetInfluences[left] = Math.max(mesh.morphTargetInfluences[left] ?? 0, blink);
      if (right !== undefined) mesh.morphTargetInfluences[right] = Math.max(mesh.morphTargetInfluences[right] ?? 0, blink);
      if (jaw !== undefined) mesh.morphTargetInfluences[jaw] = Math.max(mesh.morphTargetInfluences[jaw] ?? 0, lip);
    });
  }

  return {
    canvas,
    rig,
    timeline,
    setEmotion(next, value) {
      emotion = next;
      intensity = value;
    },
    setBlend(weights) {
      blend = weights;
    },
    setLip(amount) {
      lip = Math.max(0, Math.min(1, amount));
    },
    async showAvatar(url: string) {
      const token = ++switchToken;
      const started = performance.now();
      let pending = cache.get(url);
      if (!pending) {
        pending = new Promise((resolve, reject) => {
          new GLTFLoader().load(url, (gltf) => resolve(gltf.scene), undefined, reject);
        });
        cache.set(url, pending);
      }
      let template: THREE.Group;
      try {
        template = await pending;
      } catch {
        cache.delete(url);
        return { ok: false, loadMs: performance.now() - started, kept: true };
      }
      if (token !== switchToken) return { ok: false, loadMs: performance.now() - started, kept: true };
      const next = template.clone(true);
      next.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (!mesh.isMesh) return;
        mesh.material = Array.isArray(mesh.material) ? mesh.material.map((item) => item.clone()) : mesh.material.clone();
      });
      opacityOf(next, 0);
      scene.add(next);
      const previous = shown;
      shown = next;
      gsap.to({ value: 0 }, { value: 1, duration: 0.35, onUpdate() { opacityOf(next, this.targets()[0].value); } });
      if (previous && previous !== next) {
        gsap.to(
          { value: 1 },
          {
            value: 0,
            duration: 0.35,
            onUpdate() { opacityOf(previous, this.targets()[0].value); },
            onComplete() { scene.remove(previous); },
          },
        );
      }
      const loadMs = performance.now() - started;
      (window as Window & { __avatarState?: { url: string; loadMs: number; ok: boolean } }).__avatarState = {
        url,
        loadMs,
        ok: true,
      };
      return { ok: true, loadMs, kept: false };
    },
    setPrint(progress) {
      printProgress = progress;
    },
    setQuality(level: number) {
      if (level === qualityLevel) return;
      qualityLevel = level;
      const nextScale = level === 0 ? 1 : level === 1 ? 0.75 : 0.5;
      if (nextScale === pixelScale) return;
      pixelScale = nextScale;
      renderer.setPixelRatio(nextScale);
      renderer.setSize(width, height, false);
    },
    resize(nextWidth, nextHeight) {
      camera.aspect = nextWidth / nextHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(nextWidth, nextHeight, false);
    },
    tick(time) {
      const blink = Math.sin(time * 0.7) > 0.97 ? 1 : 0;
      leftEye.scale.y = blink ? 0.12 : 1;
      rightEye.scale.y = leftEye.scale.y;
      const breathe = 1 + Math.sin(time * 1.4) * 0.02;
      body.scale.y = breathe;
      shown.rotation.y = Math.sin(time * 0.35) * rig.sway;
      shown.rotation.z = Math.sin(time * 0.2) * 0.02;
      shown.position.y = Math.sin(time * 1.4) * 0.03;
      applyBlend(shown, blink);
      lip = Math.max(0, lip - 0.02);
      const jawOpen = emotion === "awe" || emotion === "hype" ? 0.35 + intensity * 0.5 : intensity * 0.25;
      if (head.morphTargetInfluences) head.morphTargetInfluences[0] = Math.max(jawOpen, lip);
      brow.position.y = 0.28 + (emotion === "alert" ? 0.04 : intensity * 0.03);
      browR.position.y = brow.position.y;
      const tint = new THREE.Color(EMOTION_COLOR[emotion] ?? EMOTION_COLOR.ambient);
      key.color.copy(tint);
      camera.position.z = rig.camZ - intensity * 0.25;
      printBlock.scale.y = Math.max(0.04, (rig.print * 0.5 + printProgress / 100) * 1.2);
      printBlock.position.y = -1.4 + printBlock.scale.y * 0.5;
      renderer.render(scene, camera);
    },
  };
}

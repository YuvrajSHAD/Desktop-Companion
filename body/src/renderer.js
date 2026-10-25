import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const api = window.petAPI;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const damp = (cur, target, k, dt) => cur + (target - cur) * (1 - Math.exp(-k * dt));
const rnd = (a, b) => a + Math.random() * (b - a);
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

const BONES = [
  'hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
  'leftShoulder', 'rightShoulder', 'leftUpperArm', 'rightUpperArm', 'leftLowerArm', 'rightLowerArm',
  'leftHand', 'rightHand', 'leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg',
  'leftFoot', 'rightFoot',
];

const MOOD = {
  neutral: {},
  happy: { happy: 0.6 },
  sad: { sad: 0.7 },
  angry: { angry: 0.55 },
  surprised: { surprised: 0.75 },
  relaxed: { relaxed: 0.8 },
  sleepy: { relaxed: 0.5, _eyes: 0.5 },
};

const LINES = {
  pat: ['Mm. That is nice.', 'Careful, I might fall asleep.', 'Slow down. I am savouring this.', 'Okay, you can stay.'],
  poke: ['Oh! Hello.', 'I was resting my eyes.', 'Rude. Gently, but rude.', 'Yes? I am listening. Slowly.'],
  annoyed: ['Okay, okay. I am up.', 'That is a lot of poking for a sloth.'],
  grab: ['Whoa, slowly...', 'I can walk, you know. Eventually.'],
};

async function main() {
  const cfg = await api.getConfig();
  const { W, H, row, ppm, heightM } = cfg;

  /* ---------------- three.js scene ---------------- */
  const canvas = document.getElementById('c');
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setSize(W, H, false);
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-W / 2 / ppm, W / 2 / ppm, row / ppm, -(H - row) / ppm, 0.1, 50);
  camera.position.set(0, 0, 10);
  const sun = new THREE.DirectionalLight(0xffffff, Math.PI);
  sun.position.set(0.6, 1.0, 1.4);
  scene.add(sun);
  scene.add(new THREE.AmbientLight(0xffffff, 0.35));

  const pivot = new THREE.Group();
  scene.add(pivot);
  const lookTarget = new THREE.Object3D();
  scene.add(lookTarget);

  /* ---------------- bubble / zzz ---------------- */
  const bubble = document.getElementById('bubble');
  const bubHeard = bubble.querySelector('.heard');
  const bubSaid = bubble.querySelector('.said');
  const zzz = document.getElementById('zzz');
  let said = '';
  let saidUntil = 0;
  let heard = '';
  let heardUntil = 0;
  let lastBubbleKey = '';

  const say = (text, ms) => {
    said = text;
    saidUntil = performance.now() + ms;
  };

  /* ---------------- state from main / brain ---------------- */
  let pet = { mode: 'fall', facing: 1, vx: 0, vy: 0, grounded: false, cx: W / 2, cy: row, landedAgo: 99, landSpeed: 0 };
  api.onPet((s) => { pet = s; });

  let voice = 'idle';
  let mood = 'neutral';
  let moodUntil = 0;
  let mouthTarget = 0;
  let lastMouthAt = 0;
  let reaction = null; // { name, until }
  const SIZES = { normal: 1, chibi: 0.55, big: 1.3 };
  let sizeMode = 'normal';
  let sizeCur = 1;
  let lastBeatMs = 0; // when the last music beat arrived
  let beatN = 0;
  let musicBpm = 120;
  let danceBob = 0; // vertical squat of the whole body while dancing (metres, before size scale)
  let danceYaw = 0;
  const react = (name, secs) => { reaction = { name, until: performance.now() + secs * 1000 }; };

  api.onEvent((m) => {
    const now = performance.now();
    switch (m.type) {
      case 'state':
        if (m.value === 'thinking' || m.value === 'listening') { said = ''; saidUntil = 0; }
        if (m.value === 'idle' && voice === 'speaking') {
          moodUntil = now + 2500;
          saidUntil = now + 3000 + 45 * said.length;
        }
        if (m.value === 'speaking') { moodUntil = Infinity; saidUntil = Infinity; }
        voice = m.value;
        break;
      case 'emotion':
        mood = MOOD[m.value] ? m.value : 'neutral';
        moodUntil = Infinity;
        break;
      case 'subtitle':
        said = (voice === 'speaking' && said ? said + ' ' : '') + m.text;
        if (said.length > 230) said = said.slice(said.length - 230).replace(/^\S*\s/, '');
        saidUntil = Infinity;
        break;
      case 'heard':
        heard = m.text;
        heardUntil = now + 6000;
        break;
      case 'size':
        if (SIZES[m.value]) sizeMode = m.value;
        break;
      case 'music':
        if (m.bpm) musicBpm = m.bpm;
        if (m.beat) { lastBeatMs = now; beatN++; }
        break;
      case 'mouth':
        mouthTarget = m.v;
        lastMouthAt = now;
        break;
    }
  });

  /* ---------------- load the VRM ---------------- */
  const model = await api.getModel();
  if (!model) {
    say('Put a .vrm file in the models folder and restart me.', 1e9);
    drawBubble(0, 0);
    api.ready();
    return;
  }
  const loader = new GLTFLoader();
  loader.register((p) => new VRMLoaderPlugin(p));
  const u8 = model.data;
  const ab = u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength);
  const gltf = await new Promise((res, rej) => loader.parse(ab, '', res, rej));
  const vrm = gltf.userData.vrm;
  if (VRMUtils.removeUnnecessaryVertices) VRMUtils.removeUnnecessaryVertices(gltf.scene);
  if (VRMUtils.combineSkeletons) VRMUtils.combineSkeletons(gltf.scene);
  VRMUtils.rotateVRM0(vrm); // no-op for VRM 1.0, turns VRM 0.x models to face the camera
  vrm.scene.traverse((o) => { o.frustumCulled = false; });
  pivot.add(vrm.scene);

  // normalise size: feet on y=0, heightM tall
  vrm.scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const k = heightM / Math.max(0.1, box.max.y - box.min.y);
  vrm.scene.scale.setScalar(k);
  vrm.scene.updateMatrixWorld(true);
  box.setFromObject(vrm.scene);
  vrm.scene.position.y -= box.min.y;
  pivot.updateMatrixWorld(true);

  if (vrm.lookAt) vrm.lookAt.target = lookTarget;

  // let emotions and lip-sync mix instead of one blocking the other
  const em = vrm.expressionManager;
  if (em) {
    for (const n of ['happy', 'angry', 'sad', 'relaxed', 'surprised']) {
      const e = em.getExpression(n);
      if (e) e.overrideMouth = 'none';
    }
  }

  const B = {};
  for (const n of BONES) B[n] = vrm.humanoid.getNormalizedBoneNode(n);
  const v1 = new THREE.Vector3();
  const v2 = new THREE.Vector3();

  const hipsY = B.hips ? B.hips.getWorldPosition(v1).y : 0.85;
  const sitDrop = Math.max(0, hipsY - 0.07);

  // Work out which way each joint bends, so any VRM rig works without hard-coded signs.
  function probe(node, axis, probeN, refN, coord, wantPositive) {
    const n = B[node], p = B[probeN], r = B[refN];
    if (!n || !p || !r) return 1;
    const old = n.rotation[axis];
    n.rotation[axis] = old + 0.6;
    pivot.updateMatrixWorld(true);
    const d = p.getWorldPosition(v1)[coord] - r.getWorldPosition(v2)[coord];
    n.rotation[axis] = old;
    pivot.updateMatrixWorld(true);
    return (d > 0) === wantPositive ? 1 : -1;
  }
  const ARM = 1.38;
  const SIT_UP = 1.42, SIT_KNEE = 0.22;
  const S = {};
  for (const s of ['left', 'right']) {
    S[s] = {};
    S[s].arm = probe(s + 'UpperArm', 'z', s + 'Hand', s + 'UpperArm', 'y', false); // z*sign lowers the arm
    if (B[s + 'UpperArm']) B[s + 'UpperArm'].rotation.z = S[s].arm * ARM;
    pivot.updateMatrixWorld(true);
    S[s].elbow = probe(s + 'LowerArm', 'y', s + 'Hand', s + 'LowerArm', 'z', true); // bends forward
    S[s].armFwd = probe(s + 'UpperArm', 'x', s + 'Hand', s + 'UpperArm', 'z', true); // swings forward
    S[s].legF = probe(s + 'UpperLeg', 'x', s + 'Foot', s + 'UpperLeg', 'z', true); // swings forward
    S[s].knee = probe(s + 'LowerLeg', 'x', s + 'Foot', s + 'LowerLeg', 'z', false); // bends backward
    if (B[s + 'UpperArm']) B[s + 'UpperArm'].rotation.z = 0;
  }
  pivot.updateMatrixWorld(true);

  /* ---------------- procedural animation ---------------- */
  const T = {};
  const add = (n, x = 0, y = 0, z = 0) => {
    const a = T[n];
    if (!a) return;
    a[0] += x; a[1] += y; a[2] += z;
  };
  let walkPhase = 0;

  function buildTargets(t, mouthEnv) {
    for (const n of BONES) T[n] = [0, 0, 0];
    const mode = pet.mode;
    if (mode !== 'dance') { danceBob = 0; danceYaw = 0; }
    const breathe = Math.sin(t * (mode === 'sleep' ? 1.1 : 1.7));
    const sway = Math.sin(t * 0.6);

    // arms: hanging by default, up when falling, dangling when held
    const armVal = mode === 'fall' ? -0.9 : mode === 'jump' ? 0.2 : mode === 'drag' ? 0.7 : ARM + 0.04 * breathe;
    for (const s of ['left', 'right']) {
      add(s + 'UpperArm', 0, 0, S[s].arm * armVal);
      add(s + 'LowerArm', 0, S[s].elbow * 0.28, 0);
    }
    add('spine', 0.012 * breathe, 0.02 * sway, 0);
    add('chest', 0.018 * breathe, 0, 0);
    add('hips', 0, 0, 0.012 * sway);

    if (mode === 'sit' || mode === 'sleep') {
      for (const [s, ph] of [['left', 0], ['right', 1.7]]) {
        // legs stretched out in front, feet resting about at seat height: nothing hangs below the surface,
        // so the taskbar can't cover them. (Tune SIT_UP / SIT_KNEE: bigger knee = shins hang lower.)
        add(s + 'UpperLeg', S[s].legF * SIT_UP, 0, 0);
        add(s + 'LowerLeg', S[s].knee * (SIT_KNEE + 0.05 * Math.sin(t * 1.3 + ph)), 0, 0);
        add(s + 'UpperArm', S[s].armFwd * 0.3, 0, 0);
        add(s + 'LowerArm', 0, S[s].elbow * 0.8, 0);
      }
      add('spine', 0.06, 0, 0);
    } else if (mode === 'walk') {
      const sw = Math.sin(walkPhase);
      const cw = Math.cos(walkPhase);
      add('leftUpperLeg', S.left.legF * 0.5 * sw, 0, 0);
      add('rightUpperLeg', -S.right.legF * 0.5 * sw, 0, 0);
      add('leftLowerLeg', S.left.knee * 0.8 * Math.max(0, cw), 0, 0);
      add('rightLowerLeg', S.right.knee * 0.8 * Math.max(0, -cw), 0, 0);
      add('leftUpperArm', -S.left.armFwd * 0.4 * sw, 0, 0);
      add('rightUpperArm', S.right.armFwd * 0.4 * sw, 0, 0);
      add('spine', 0.05, 0, 0);
    } else if (mode === 'fall') {
      for (const [s, ph] of [['left', 0], ['right', 2.1]]) {
        add(s + 'UpperLeg', S[s].legF * (0.35 + 0.25 * Math.sin(t * 14 + ph)), 0, 0);
        add(s + 'LowerLeg', S[s].knee * (0.5 + 0.4 * Math.sin(t * 14 + ph + 1)), 0, 0);
      }
      add('spine', -0.08, 0, 0);
    } else if (mode === 'jump') {
      for (const s of ['left', 'right']) {
        add(s + 'UpperLeg', S[s].legF * 0.7, 0, 0);
        add(s + 'LowerLeg', S[s].knee * 1.0, 0, 0);
      }
      add('spine', 0.1, 0, 0);
    } else if (mode === 'dance') {
      dancePose(t);
    } else if (mode === 'drag') {
      for (const [s, ph] of [['left', 0], ['right', 1.3]]) {
        add(s + 'UpperLeg', S[s].legF * 0.12, 0, 0);
        add(s + 'LowerLeg', S[s].knee * (0.25 + 0.2 * Math.sin(t * 3 + ph)), 0, 0);
      }
    }

    // talking gestures
    if (voice === 'speaking' && (mode === 'idle' || mode === 'sit')) {
      const gl = Math.max(0, Math.sin(t * 1.9)) * mouthEnv;
      const gr = Math.max(0, Math.sin(t * 1.9 + 2.4)) * mouthEnv;
      add('leftLowerArm', 0, S.left.elbow * (0.2 + 0.7 * gl), 0);
      add('rightLowerArm', 0, S.right.elbow * (0.2 + 0.7 * gr), 0);
      add('leftUpperArm', S.left.armFwd * 0.25 * gl, 0, 0);
      add('rightUpperArm', S.right.armFwd * 0.25 * gr, 0, 0);
      add('head', 0.05 * Math.sin(t * 7) * mouthEnv, 0, 0);
    }
    // attentive lean while you talk
    if (voice === 'listening' && (mode === 'idle' || mode === 'sit')) {
      add('spine', 0.07, 0, 0);
      add('head', 0, 0, 0.08);
    }
    // reactions
    const nowMs = performance.now();
    if (reaction && nowMs < reaction.until) {
      const left = (reaction.until - nowMs) / 1000;
      if (reaction.name === 'pat') add('head', 0.16 * Math.min(1, left * 2), 0, 0);
      if (reaction.name === 'poke' || reaction.name === 'annoyed') add('spine', -0.1 * Math.min(1, left * 2), 0, 0);
    }
    if (mode === 'sleep') {
      add('head', 0.55, 0, 0.1);
      add('neck', 0.15, 0, 0);
      add('spine', 0.1, 0, 0);
    }
  }

  // Procedural dances locked to the music's beat. Three styles; more are just more branches.
  function dancePose(t) {
    const spb = 60 / clamp(musicBpm, 70, 180);
    const since = (performance.now() - lastBeatMs) / 1000;
    const live = since < 2.5; // real beats are arriving; otherwise keep a steady clock so it never freezes
    const beats = live ? since / spb : t / spb;
    const bp = beats % 1; // 0..1 inside the current beat
    const idx = (live ? beatN : 0) + Math.floor(beats); // beat counter
    const pulse = Math.exp(-bp * 4); // 1 right on the beat, fading out
    const side = idx % 2 ? 1 : -1; // flips every beat
    const ph = (((idx % 2) + bp) / 2) * Math.PI * 2; // one full cycle every two beats
    const style = pet.dance || 'hiphop';
    const L = 'left';
    const R = 'right';
    if (style === 'hiphop') {
      danceBob = -0.05 * pulse;
      danceYaw = 0.18 * side * (1 - bp);
      for (const s of [L, R]) {
        add(s + 'UpperLeg', S[s].legF * (0.22 + 0.3 * pulse), 0, 0);
        add(s + 'LowerLeg', S[s].knee * (0.35 + 0.55 * pulse), 0, 0);
        const up = (s === L) === (side > 0) ? pulse : 0.25; // pump one arm per beat
        add(s + 'UpperArm', 0, 0, S[s].arm * -0.95 * up);
        add(s + 'LowerArm', 0, S[s].elbow * (0.5 + 0.8 * up), 0);
      }
      add('spine', 0.06 + 0.1 * pulse, 0, 0);
      add('chest', 0.05 * pulse, 0, 0);
      add('head', 0.14 * pulse, 0, 0.06 * side);
      add('hips', 0, 0, 0.08 * side * (1 - bp));
    } else if (style === 'salsa') {
      const sw = Math.sin(ph);
      const tw = Math.sin(ph + Math.PI / 2);
      danceBob = -0.012 - 0.012 * Math.sin(ph * 2);
      danceYaw = 0.3 * tw;
      add('hips', 0, 0.28 * tw, 0.14 * sw);
      add('spine', 0, -0.16 * tw, -0.05 * sw);
      add('chest', 0, -0.1 * tw, 0);
      add('head', 0, 0, 0.07 * sw);
      add('leftUpperLeg', S.left.legF * 0.3 * Math.max(0, sw), 0, 0);
      add('rightUpperLeg', S.right.legF * 0.3 * Math.max(0, -sw), 0, 0);
      add('leftLowerLeg', S.left.knee * 0.3 * Math.max(0, sw), 0, 0);
      add('rightLowerLeg', S.right.knee * 0.3 * Math.max(0, -sw), 0, 0);
      for (const s of [L, R]) {
        add(s + 'UpperArm', S[s].armFwd * 0.3 * (s === L ? sw : -sw), 0, S[s].arm * -0.6);
        add(s + 'LowerArm', 0, S[s].elbow * (0.7 + 0.3 * Math.sin(ph * 2)), 0);
      }
    } else {
      // shuffle: quick alternating foot slides, loose swinging arms
      const st = Math.sin(ph);
      danceBob = -0.018 * Math.abs(st);
      danceYaw = 0.22 * st;
      add('leftUpperLeg', S.left.legF * 0.5 * Math.max(0, st), 0, 0);
      add('rightUpperLeg', S.right.legF * 0.5 * Math.max(0, -st), 0, 0);
      add('leftLowerLeg', S.left.knee * 0.4 * Math.max(0, st), 0, 0);
      add('rightLowerLeg', S.right.knee * 0.4 * Math.max(0, -st), 0, 0);
      add('hips', 0, 0.18 * st, 0.06 * st);
      add('spine', 0.12, 0, 0);
      add('head', 0.08 + 0.05 * pulse, 0, 0);
      for (const s of [L, R]) {
        const dir = s === L ? st : -st;
        add(s + 'UpperArm', S[s].armFwd * 0.55 * dir, 0, S[s].arm * -0.4);
        add(s + 'LowerArm', 0, S[s].elbow * 0.6, 0);
      }
    }
  }

  function applyTargets(dt) {
    const a = 1 - Math.exp(-11 * dt);
    for (const n of BONES) {
      const node = B[n];
      if (!node) continue;
      const tg = T[n];
      const c = node.rotation;
      c.x += (tg[0] - c.x) * a;
      c.y += (tg[1] - c.y) * a;
      c.z += (tg[2] - c.z) * a;
    }
  }

  // head / eyes follow the real desktop cursor
  let lookYaw = 0;
  let lookPitch = 0;
  function look(dt, t) {
    const hp = B.head ? B.head.getWorldPosition(v1) : v1.set(0, 1.4, 0);
    const wx = (pet.cx - W / 2) / ppm;
    const wy = (row - pet.cy) / ppm;
    lookTarget.position.set(clamp(wx, -3, 3), clamp(wy, -3, 3), 1.4);
    let yaw = Math.atan2(wx - hp.x, 1.4) - pivot.rotation.y;
    let pitch = -Math.atan2(wy - hp.y, 1.4);
    let gain = 1;
    if (voice === 'speaking') {
      // talking: look at the person (the camera), not at the mouse
      lookTarget.position.set(hp.x, hp.y, 6);
      yaw = 0; pitch = 0; gain = 1;
    }
    if (voice === 'thinking') { yaw = -0.3; pitch = -0.22; gain = 1; }
    if (pet.mode === 'sleep') gain = 0;
    if (pet.mode === 'fall' || pet.mode === 'drag' || pet.mode === 'jump') gain = 0.3;
    if (pet.mode === 'dance') gain = 0.45;
    yaw *= gain;
    pitch = pitch * gain;
    lookYaw = damp(lookYaw, yaw, 7, dt);
    lookPitch = damp(lookPitch, pitch, 7, dt);
    const yw = clamp(lookYaw, -1, 1);
    const pt = clamp(lookPitch, -0.7, 0.7);
    if (B.head) { T.head[1] += yw * 0.5; T.head[0] += pt * 0.45; }
    if (B.neck) { T.neck[1] += yw * 0.3; T.neck[0] += pt * 0.3; }
    if (B.chest) T.chest[1] += yw * 0.1;
    if (B.spine) T.spine[1] += yw * 0.08;
    // idle micro-motion so it never looks frozen
    if (B.head) { T.head[1] += 0.03 * Math.sin(t * 0.7); T.head[2] += 0.02 * Math.sin(t * 0.5 + 1); }
  }

  /* ---------------- expressions ---------------- */
  const cur = { happy: 0, sad: 0, angry: 0, surprised: 0, relaxed: 0 };
  let eyesClosed = 0;
  let blinkT = rnd(1.5, 4);
  let blinkPhase = -1;
  let blinkAnim = 0;
  let mouth = 0;

  function expressionTargets(now) {
    const e = { happy: 0, sad: 0, angry: 0, surprised: 0, relaxed: 0 };
    let eyes = 0;
    const apply = (o) => {
      for (const key in o) {
        if (key === '_eyes') eyes = Math.max(eyes, o[key]);
        else e[key] = Math.max(e[key], o[key]);
      }
    };
    if (now < moodUntil || voice === 'speaking') apply(MOOD[mood] || {});
    if (voice === 'listening') apply({ relaxed: 0.25 });
    if (voice === 'thinking') apply({ relaxed: 0.2 });
    if (pet.mode === 'fall') apply({ surprised: 0.8 });
    if (pet.mode === 'drag') apply({ surprised: 0.45 });
    if (pet.mode === 'dance') apply({ happy: 0.55 });
    if (pet.mode === 'sleep') { apply({ relaxed: 0.5 }); eyes = 1; }
    if (pet.mode === 'sit' && voice === 'idle') apply({ relaxed: 0.2 });
    if (reaction && now < reaction.until) {
      if (reaction.name === 'pat') apply({ happy: 1 });
      if (reaction.name === 'poke') apply({ surprised: 0.9 });
      if (reaction.name === 'annoyed') apply({ angry: 0.6 });
    }
    return { e, eyes };
  }

  function updateExpressions(dt, t, now) {
    if (!em) return;
    const { e, eyes } = expressionTargets(now);
    for (const n in cur) {
      cur[n] = damp(cur[n], e[n], 8, dt);
      em.setValue(n, cur[n]);
    }
    eyesClosed = damp(eyesClosed, eyes, 5, dt);
    blinkT -= dt;
    if (blinkT <= 0 && blinkPhase < 0) { blinkPhase = 0; blinkT = rnd(2.2, 5.5); }
    if (blinkPhase >= 0) {
      blinkPhase += dt / 0.17;
      blinkAnim = blinkPhase < 0.5 ? blinkPhase * 2 : 2 - blinkPhase * 2;
      if (blinkPhase >= 1) { blinkPhase = -1; blinkAnim = 0; }
    }
    em.setValue('blink', Math.max(blinkAnim, eyesClosed));

    // lip-sync driven by the real audio level coming from the voice engine
    if (now - lastMouthAt > 200) mouthTarget = 0;
    mouth = damp(mouth, mouthTarget, mouthTarget > mouth ? 28 : 12, dt);
    const m = mouth;
    em.setValue('aa', clamp(m * (0.55 + 0.45 * Math.abs(Math.sin(t * 7.1))), 0, 1));
    em.setValue('oh', clamp(m * 0.5 * Math.max(0, Math.sin(t * 4.3 + 1)), 0, 1));
    em.setValue('ih', clamp(m * 0.3 * Math.max(0, Math.sin(t * 5.9 + 2)), 0, 1));
    em.setValue('ee', clamp(m * 0.25 * Math.max(0, Math.sin(t * 3.7 + 4)), 0, 1));
    em.setValue('ou', clamp(m * 0.3 * Math.max(0, Math.sin(t * 2.9 + 3)), 0, 1));
  }

  /* ---------------- bubble drawing ---------------- */
  function headScreen() {
    const hp = B.head ? B.head.getWorldPosition(v1) : v1.set(0, 1.5, 0);
    return { x: W / 2 + hp.x * ppm, y: row - hp.y * ppm };
  }

  function drawBubble(hx, hy) {
    const now = performance.now();
    const thinking = voice === 'thinking';
    const showSaid = said && now < saidUntil;
    const showHeard = heard && now < heardUntil && (thinking || showSaid);
    const key = [thinking, showSaid ? said : '', showHeard ? heard : ''].join('|');
    if (key !== lastBubbleKey) {
      lastBubbleKey = key;
      bubHeard.textContent = showHeard ? 'you: ' + heard : '';
      if (thinking && !showSaid) bubSaid.innerHTML = '<span class="dots"><span>.</span><span>.</span><span>.</span></span>';
      else bubSaid.textContent = showSaid ? said : '';
      bubble.classList.toggle('show', thinking || showSaid);
    }
    if (bubble.classList.contains('show')) {
      const bw = bubble.offsetWidth;
      bubble.style.left = clamp(hx - bw / 2, 6, W - bw - 6) + 'px';
      // above the head, but never pushed off the top of the window (big-screen mode)
      bubble.style.bottom = Math.min(H - (hy - 78 * Math.max(0.6, sizeCur)), H - bubble.offsetHeight - 6) + 'px';
    }
    zzz.classList.toggle('show', pet.mode === 'sleep');
    if (pet.mode === 'sleep') {
      zzz.style.left = hx + 34 + 'px';
      zzz.style.top = hy - 72 + 'px';
    }
  }

  /* ---------------- input: hover / click / drag ---------------- */
  const gl = renderer.getContext();
  const px = new Uint8Array(4);
  function hitTest(x, y) {
    const r = renderer.getPixelRatio();
    const cw = Math.floor(W * r);
    const ch = Math.floor(H * r);
    const ix = clamp(Math.floor(x * r), 0, cw - 1);
    const iy = clamp(ch - 1 - Math.floor(y * r), 0, ch - 1);
    gl.readPixels(ix, iy, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    return px[3] > 24;
  }

  const mouse = { x: -1, y: -1, dirty: false, over: false, down: false, sx: 0, sy: 0, dragging: false };
  const pokes = [];
  window.addEventListener('mousemove', (e) => {
    mouse.x = e.clientX; mouse.y = e.clientY; mouse.dirty = true;
    if (mouse.down && !mouse.dragging && Math.hypot(e.clientX - mouse.sx, e.clientY - mouse.sy) > 6) {
      mouse.dragging = true;
      api.dragStart(mouse.sx, mouse.sy);
      if (voice === 'idle' && Math.random() < 0.5) say(pick(LINES.grab), 2600);
    }
  });
  window.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || !mouse.over) return;
    mouse.down = true; mouse.sx = e.clientX; mouse.sy = e.clientY;
    if (canvas.setPointerCapture) { try { canvas.setPointerCapture(e.pointerId); } catch {} }
    api.activity();
  });
  window.addEventListener('pointerup', (e) => {
    if (!mouse.down) return;
    mouse.down = false;
    if (mouse.dragging) { mouse.dragging = false; api.dragEnd(); return; }
    clicked(e.clientX, e.clientY);
  });
  window.addEventListener('contextmenu', (e) => { e.preventDefault(); if (mouse.over) api.contextMenu(); });
  document.addEventListener('mouseleave', () => {
    if (!mouse.down && !mouse.dragging) { mouse.over = false; api.setIgnore(true); }
  });

  function clicked(x, y) {
    const hs = headScreen();
    const isHead = Math.hypot(x - hs.x, y - (hs.y - 8 * sizeCur)) < 0.17 * ppm * sizeCur;
    const now = performance.now();
    api.activity();
    if (isHead) {
      react('pat', 2.2);
      if (voice === 'idle' && Math.random() < 0.7) say(pick(LINES.pat), 2800);
      api.toBrain({ type: 'touch', kind: 'pat' });
    } else {
      pokes.push(now);
      while (pokes.length && now - pokes[0] > 4000) pokes.shift();
      if (pokes.length >= 4) {
        react('annoyed', 2.5);
        if (voice === 'idle') say(pick(LINES.annoyed), 2800);
        pokes.length = 0;
      } else {
        react('poke', 1.0);
        if (voice === 'idle' && Math.random() < 0.6) say(pick(LINES.poke), 2600);
      }
      api.toBrain({ type: 'touch', kind: 'poke' });
    }
  }

  /* ---------------- main loop ---------------- */
  let last = performance.now();
  let t = 0;
  let readySent = false;

  function frame() {
    requestAnimationFrame(frame);
    const now = performance.now();
    const calm = voice === 'idle' && (pet.mode === 'idle' || pet.mode === 'sit' || pet.mode === 'sleep');
    const fps = pet.mode === 'sleep' && voice === 'idle' ? 15 : calm ? 30 : 60;
    if (now - last < 1000 / fps - 3) return;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    t += dt;

    if (pet.mode === 'walk') walkPhase += dt * 5.0;
    const mouthEnv = clamp(mouth * 1.6, 0, 1);

    buildTargets(t, mouthEnv);
    look(dt, t);
    applyTargets(dt);

    // body yaw: face the way it walks, otherwise lean toward the cursor
    const yawGoal =
      pet.mode === 'walk' ? pet.facing * 1.05
      : pet.mode === 'dance' ? danceYaw
      : pet.mode === 'idle' || pet.mode === 'sit' ? clamp(lookYaw * 0.3, -0.35, 0.35)
      : 0;
    pivot.rotation.y = damp(pivot.rotation.y, yawGoal, 6, dt);

    // sit drop, walking bob, and a bit of inertia so hair/skirt springs actually swing when the window moves
    const bob = pet.mode === 'walk' ? 0.012 * Math.abs(Math.sin(walkPhase)) : 0;
    const dropGoal = pet.mode === 'sit' || pet.mode === 'sleep' ? -sitDrop : 0;
    sizeCur = damp(sizeCur, SIZES[sizeMode], 6, dt);
    pivot.position.y = damp(pivot.position.y, (dropGoal + bob + danceBob) * sizeCur, pet.mode === 'dance' ? 22 : 9, dt);
    const inertia = -clamp(pet.vx * 0.00035, -0.12, 0.12);
    pivot.position.x = damp(pivot.position.x, inertia * sizeCur, 6, dt);
    const roll = pet.mode === 'drag' || pet.mode === 'fall' ? -clamp(pet.vx * 0.0003, -0.25, 0.25) : 0;
    pivot.rotation.z = damp(pivot.rotation.z, roll, 8, dt);
    const squash = Math.max(0, 1 - pet.landedAgo / 0.25) * clamp(pet.landSpeed / 2500, 0, 1) * 0.08;
    pivot.scale.set(sizeCur * (1 + squash * 0.5), sizeCur * (1 - squash), sizeCur);

    updateExpressions(dt, t, now);
    vrm.update(dt);
    renderer.render(scene, camera);

    // per-pixel click-through: the window only catches the mouse while it is over the character
    // (uses the cursor position the main process polls, because Windows stops forwarding mouse events to a
    // click-through window after it has been in the background for a while, which made her undraggable)
    if (!mouse.dragging && !mouse.down) {
      const inside = pet.cx >= 0 && pet.cy >= 0 && pet.cx < W && pet.cy < H;
      const over = inside && hitTest(pet.cx, pet.cy);
      mouse.x = pet.cx; mouse.y = pet.cy;
      if (over !== mouse.over) {
        mouse.over = over;
        api.setIgnore(!over);
        document.body.style.cursor = over ? 'grab' : 'default';
      }
    }

    const hs = headScreen();
    drawBubble(hs.x, hs.y);

    if (!readySent && t > 0.3) { readySent = true; api.ready(); }
  }
  requestAnimationFrame(frame);
}

main().catch((e) => {
  console.error('[body] renderer failed:', e);
  const b = document.getElementById('bubble');
  b.querySelector('.said').textContent = 'Renderer error: ' + (e && e.message ? e.message : e);
  b.classList.add('show');
  b.style.left = '10px';
  b.style.bottom = '300px';
});

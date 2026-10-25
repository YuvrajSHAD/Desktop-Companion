'use strict';
/*
 * Electron main process: owns the transparent window, the physics loop, the tray,
 * and the (token-authenticated, localhost-only) WebSocket link to the Python brain.
 */
const { app, BrowserWindow, ipcMain, screen, Tray, Menu, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const WebSocket = require('ws');
const { Pet } = require('./behavior');

const cfg = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));
const ROOT = path.join(__dirname, '..');
const MODELS_DIR = path.join(ROOT, 'models');
const TOKEN_FILE = path.join(ROOT, '.bridge_token');
const { w: W, h: H, row: ROW } = cfg.window;

const TEST_SHOT = process.env.PET_SHOT || '';          // test hook: save a screenshot and quit
const TEST_MODE = process.env.PET_TEST_MODE || '';     // test hook: force a pose
if (TEST_SHOT) {
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch('enable-unsafe-swiftshader');
  app.commandLine.appendSwitch('use-gl', 'angle');
  app.commandLine.appendSwitch('use-angle', 'swiftshader');
  app.commandLine.appendSwitch('no-sandbox');
  app.commandLine.appendSwitch('disable-gpu-sandbox');
}

if (!app.requestSingleInstanceLock()) app.quit();

let win = null;
let tray = null;
let link = null; // WebSocket to the brain
let hidden = false;
let hiddenByFullscreen = false;
let pyWins = [];
let lastFloors = [];
let floorsAt = 0;
let dragging = false;
let sizeMode = 'normal'; // normal | chibi | big
let danceEnabled = true;
let testBeatTimer = null;

const pet = new Pet({ W, row: ROW, sleepAfter: cfg.sleepAfterSec, walkSpeed: cfg.walkSpeed });

/* ---------------- world model ---------------- */

function displayBounds() {
  const ds = screen.getAllDisplays();
  const b = { l: Infinity, t: Infinity, r: -Infinity, b: -Infinity };
  for (const d of ds) {
    b.l = Math.min(b.l, d.bounds.x);
    b.t = Math.min(b.t, d.bounds.y);
    b.r = Math.max(b.r, d.bounds.x + d.bounds.width);
    b.b = Math.max(b.b, d.bounds.y + d.bounds.height);
  }
  return b;
}

function floors() {
  const now = Date.now();
  if (now - floorsAt < 1000) return lastFloors;
  floorsAt = now;
  lastFloors = screen.getAllDisplays().map((d) => {
    const wl = d.workArea.x;
    const wr = d.workArea.x + d.workArea.width;
    return { id: 'floor:' + d.id, wl, wr, y: d.workArea.y + d.workArea.height, vis: [[wl, wr]], floor: true };
  });
  return lastFloors;
}

function toDip(pt) {
  try {
    return screen.screenToDipPoint(pt);
  } catch {
    return pt; // non-Windows: no conversion needed
  }
}

// Python reports physical pixels; Electron wants DIPs.
function convertWindows(msg) {
  const out = [];
  for (const w of msg.wins || []) {
    const p1 = toDip({ x: w.l, y: w.y });
    const p2 = toDip({ x: w.r, y: w.y });
    const d = screen.getDisplayNearestPoint({ x: p1.x, y: p1.y });
    if (p1.y - d.bounds.y < cfg.headroom) continue; // no room above for the character (e.g. maximised window)
    const vis = (w.vis || []).map(([a, b]) => [
      toDip({ x: a, y: w.y }).x,
      toDip({ x: b, y: w.y }).x,
    ]);
    if (vis.length) out.push({ id: 'w' + w.id, wl: p1.x, wr: p2.x, y: p1.y, vis, fg: !!w.fg, floor: false });
  }
  return out;
}

/* ---------------- link to the Python brain ---------------- */

function ownHwnd() {
  try {
    const b = win.getNativeWindowHandle();
    return b.length >= 8 ? Number(b.readBigUInt64LE(0)) : b.readUInt32LE(0);
  } catch {
    return 0;
  }
}

function connect() {
  let token;
  try {
    token = fs.readFileSync(TOKEN_FILE, 'utf8').trim();
  } catch {
    return setTimeout(connect, 2000); // brain not running yet
  }
  const ws = new WebSocket(cfg.ws);
  ws.on('open', () => {
    ws.send(JSON.stringify({ type: 'hello', token, hwnd: ownHwnd() }));
    link = ws;
  });
  ws.on('message', (data) => {
    let m;
    try {
      m = JSON.parse(data.toString());
    } catch {
      return;
    }
    onBrain(m);
  });
  ws.on('close', () => {
    if (link === ws) link = null;
    setTimeout(connect, 2000);
  });
  ws.on('error', () => {});
}

function onBrain(m) {
  if (m.type === 'windows') {
    pyWins = convertWindows(m);
    setFullscreen(!!m.fullscreen);
    return;
  }
  if (m.type === 'music') {
    if (!danceEnabled) return;
    if (m.beat === undefined) pet.setMusic(!!m.active); // active/inactive change
    else if (!pet.music) pet.setMusic(true);
  }
  if (m.type === 'state') {
    pet.busy = m.value !== 'idle';
    if (pet.busy) pet.activity();
  }
  if (win && !win.isDestroyed()) win.webContents.send('evt', m);
}

function setFullscreen(fs_) {
  if (!win || win.isDestroyed()) return;
  if (fs_ && !hidden && !hiddenByFullscreen) {
    hiddenByFullscreen = true;
    win.hide();
  } else if (!fs_ && hiddenByFullscreen) {
    hiddenByFullscreen = false;
    if (!hidden) win.showInactive();
  }
}

/* ---------------- window + loop ---------------- */

function createWindow() {
  win = new BrowserWindow({
    width: W,
    height: H,
    x: 0,
    y: -H - 100,
    transparent: true,
    frame: false,
    resizable: false,
    hasShadow: false,
    skipTaskbar: true,
    focusable: false, // clicking the pet never steals focus, so "active window" stays your real window
    alwaysOnTop: true,
    show: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  win.setAlwaysOnTop(true, 'screen-saver'); // above the taskbar too
  win.setIgnoreMouseEvents(true, { forward: true });
  win.loadFile(path.join(__dirname, 'index.html'));
  win.once('ready-to-show', () => win.showInactive());
}

let last = process.hrtime.bigint();
let lastBounds = '';
let sendAcc = 0;

function tick() {
  if (!win || win.isDestroyed()) return;
  const nowT = process.hrtime.bigint();
  const dt = Math.min(0.05, Number(nowT - last) / 1e9);
  last = nowT;

  const cursor = screen.getCursorScreenPoint();
  const surfaces = pyWins.concat(floors());
  pet.update(dt, { cursor, bounds: displayBounds(), surfaces });

  const o = pet.windowOrigin();
  const key = Math.round(o.x) + ',' + Math.round(o.y);
  if (key !== lastBounds) {
    lastBounds = key;
    win.setBounds({ x: Math.round(o.x), y: Math.round(o.y), width: W, height: H });
  }

  sendAcc += dt;
  const moving = ['drag', 'fall', 'jump', 'walk', 'dance'].includes(pet.mode);
  if (sendAcc >= (moving ? 1 / 60 : 1 / 30)) {
    sendAcc = 0;
    win.webContents.send('pet', pet.state(cursor));
  }
}

/* ---------------- IPC ---------------- */

ipcMain.handle('config', () => ({ W, H, row: ROW, ppm: cfg.ppm, heightM: cfg.heightM }));

ipcMain.handle('model', () => {
  let files = [];
  try {
    files = fs.readdirSync(MODELS_DIR).filter((f) => f.toLowerCase().endsWith('.vrm'));
  } catch {}
  if (!files.length) return null;
  const pick = files.find((f) => f.toLowerCase() === 'character.vrm') || files.sort()[0];
  return { name: pick, data: fs.readFileSync(path.join(MODELS_DIR, pick)) };
});

ipcMain.on('ignore', (_e, v) => {
  if (!win || win.isDestroyed() || dragging) return;
  if (v) win.setIgnoreMouseEvents(true, { forward: true });
  else win.setIgnoreMouseEvents(false);
});
ipcMain.on('drag-start', (_e, { gx, gy }) => {
  dragging = true;
  if (win) win.setIgnoreMouseEvents(false);
  pet.grab(gx, gy);
});
ipcMain.on('drag-end', () => {
  dragging = false;
  pet.release();
});
ipcMain.on('activity', () => pet.activity());
ipcMain.on('to-brain', (_e, msg) => {
  if (link && link.readyState === WebSocket.OPEN) link.send(JSON.stringify(msg));
});
ipcMain.on('context-menu', () => buildMenu().popup({ window: win }));
ipcMain.on('renderer-ready', () => {
  sendEvt({ type: 'size', value: sizeMode });
  if (!TEST_SHOT) return;
  const at = Number(process.env.PET_SHOT_AT || 4500);
  setTimeout(() => {
    if (TEST_MODE === 'walk') {
      pet.force('idle');
      pet.mode = 'walk';
      pet.walkUntil = 1e9;
    } else if (TEST_MODE === 'fall') {
      pet.y -= 1800;
      pet._startFall();
    } else if (TEST_MODE) {
      pet.force(TEST_MODE);
    }
    if (process.env.PET_TEST_SPEAK) {
      const send = (m) => win.webContents.send('evt', m);
      send({ type: 'state', value: 'speaking' });
      send({ type: 'emotion', value: process.env.PET_TEST_SPEAK });
      send({ type: 'heard', text: 'hey, how are you doing today?' });
      send({ type: 'subtitle', text: "I'm doing well, just hanging out up here." });
      setInterval(() => send({ type: 'mouth', v: 0.7 + 0.3 * Math.sin(Date.now() / 90) }), 40);
    }
  }, 1800);
  setTimeout(async () => {
    const img = await win.webContents.capturePage();
    fs.writeFileSync(TEST_SHOT, img.toPNG());
    fs.writeFileSync(TEST_SHOT + '.json', JSON.stringify({
      mode: pet.mode, surfaceId: pet.surfaceId, x: pet.x, y: pet.y, linked: !!link, busy: pet.busy,
    }));
    app.quit();
  }, at);
});

/* ---------------- tray / menu ---------------- */

function sendEvt(m) {
  if (win && !win.isDestroyed()) win.webContents.send('evt', m);
}

function setSize(mode) {
  sizeMode = mode;
  sendEvt({ type: 'size', value: mode });
}

// Menu test: fake a 120 bpm track for 20 s so you can see the dances without playing anything.
function danceNow() {
  if (testBeatTimer) clearInterval(testBeatTimer);
  danceEnabled = true;
  pet.setMusic(true);
  const t0 = Date.now();
  testBeatTimer = setInterval(() => {
    if (Date.now() - t0 > 20000) {
      clearInterval(testBeatTimer);
      testBeatTimer = null;
      pet.setMusic(false);
      return;
    }
    sendEvt({ type: 'music', active: true, beat: true, level: 0.8, bpm: 120 });
  }, 500);
}

function toggleHidden() {
  hidden = !hidden;
  if (hidden) win.hide();
  else if (!hiddenByFullscreen) win.showInactive();
}

function buildMenu() {
  return Menu.buildFromTemplate([
    { label: hidden ? 'Show Moss' : 'Hide Moss', click: toggleHidden },
    { label: 'Sit down', click: () => pet.force('sit') },
    { label: 'Take a nap', click: () => pet.force('sleep') },
    { label: 'Stand up / wake', click: () => pet.force('idle') },
    { label: 'Jump to another window', click: () => pet.jumpSoon() },
    { label: 'Dance now (20 s test)', click: danceNow },
    { label: 'Dance to my music', type: 'checkbox', checked: danceEnabled, click: (i) => {
      danceEnabled = i.checked;
      if (!danceEnabled) pet.setMusic(false);
    } },
    { type: 'separator' },
    { label: 'Size: normal', type: 'radio', checked: sizeMode === 'normal', click: () => setSize('normal') },
    { label: 'Size: chibi', type: 'radio', checked: sizeMode === 'chibi', click: () => setSize('chibi') },
    { label: 'Size: big screen', type: 'radio', checked: sizeMode === 'big', click: () => setSize('big') },
    { type: 'separator' },
    { label: 'Drop from the top of the screen', click: () => pet.respawn(displayBounds()) },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() },
  ]);
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'assets', 'tray.png'));
  tray = new Tray(icon);
  tray.setToolTip('Moss');
  tray.on('click', toggleHidden);
  tray.on('right-click', () => tray.popUpContextMenu(buildMenu()));
}

app.whenReady().then(() => {
  createWindow();
  try {
    createTray();
  } catch (e) {
    console.warn('[body] tray unavailable:', e.message);
  }
  setInterval(tick, 16);
  connect();
});
app.on('window-all-closed', () => app.quit());

'use strict';
/*
 * Pet behaviour + physics. Pure logic: no Electron imports, so it can be unit-tested in plain Node.
 *
 * Coordinates are screen DIPs. (x, y) is the point where the pet's feet/seat touch the world:
 * x = horizontal centre of the pet window, y = the "surface row" of the window.
 *
 * Surfaces: { id, wl, wr, y, vis: [[a,b], ...], floor }
 *   wl/wr = full left/right of the thing we stand on, y = its top edge,
 *   vis   = parts of that top edge that are actually visible (not covered by other windows).
 */

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

class Pet {
  constructor(opts = {}) {
    this.o = Object.assign(
      {
        W: 440,            // window width
        row: 600,          // window row that touches the surface
        gravity: 2600,     // DIP/s^2
        maxFall: 2600,
        margin: 36,        // keep this far from the ends of a ledge
        sleepAfter: 240,   // seconds without activity before napping
        walkSpeed: 55,     // DIP/s ("slow and steady")
        rideRate: 16,      // how tightly it follows a moving window
        jumpReach: 650,    // max horizontal distance of a jump between ledges
        jumpMaxUp: 320,    // max height it will jump up
        jumpMaxDown: 700,  // max drop it will jump down
        jumpChance: 0.2,   // chance an idle decision becomes a jump (when a target exists)
        rng: Math.random,
      },
      opts
    );
    this.x = 0;
    this.y = 0;
    this.vx = 0;
    this.vy = 0;
    this.mode = 'fall'; // fall | idle | sit | walk | sleep | drag
    this.facing = 1;
    this.surfaceId = null;
    this.xRel = 0;
    this.t = 0;
    this.lastActivity = 0;
    this.busy = false; // true while the voice loop is listening/thinking/speaking
    this.nextDecision = 2;
    this.walkDir = 1;
    this.walkUntil = 0;
    this.grabPt = null;
    this.hist = [];
    this.landedAt = -10;
    this.landSpeed = 0;
    this.spawned = false;
    this.music = false;       // true while music is playing (set from the audio listener)
    this.dance = 'hiphop';    // hiphop | salsa | shuffle
    this.danceSwitchAt = 0;
    this.wantJump = false;    // set by the menu: jump to another ledge as soon as possible
    this.jumpFrom = null;
  }

  /* ---------------- public controls ---------------- */

  activity() {
    this.lastActivity = this.t;
  }

  grab(gx, gy) {
    this.mode = 'drag';
    this.grabPt = { gx, gy };
    this.surfaceId = null;
    this.hist = [];
    this.activity();
  }

  release() {
    if (this.mode !== 'drag') return;
    const h = this.hist;
    let vx = 0;
    let vy = 0;
    if (h.length >= 2) {
      const a = h[0];
      const b = h[h.length - 1];
      const dt = b.t - a.t;
      if (dt > 0.016) {
        vx = (b.x - a.x) / dt;
        vy = (b.y - a.y) / dt;
      }
    }
    this.vx = clamp(vx, -1600, 1600);
    this.vy = clamp(vy, -1600, 1600);
    this.mode = 'fall';
    this.grabPt = null;
    this.activity();
  }

  setMusic(on) {
    this.music = !!on;
  }

  jumpSoon() {
    this.wantJump = true;
  }

  force(mode) {
    if (this.surfaceId === null) return;
    this.mode = mode;
    if (mode === 'sleep') this.lastActivity = this.t - this.o.sleepAfter - 1;
    else this.activity();
    this.nextDecision = this.t + 8 + this.o.rng() * 10;
  }

  respawn(bounds) {
    this.spawned = false;
    this.mode = 'fall';
    this.surfaceId = null;
    this.vx = this.vy = 0;
    if (bounds) this._spawn(bounds);
  }

  /* ---------------- simulation ---------------- */

  update(dt, env) {
    this.t += dt;
    if (!this.spawned) this._spawn(env.bounds);
    if (this.busy) this.lastActivity = this.t;
    if (this.wantJump && this.surfaceId !== null && ['idle', 'sit', 'walk'].includes(this.mode)) {
      this.wantJump = false;
      this._tryJump(env);
    }
    switch (this.mode) {
      case 'jump':
      case 'fall':
        this._fall(dt, env);
        break;
      case 'drag':
        this._drag(dt, env);
        break;
      default:
        this._ground(dt, env);
    }
  }

  _spawn(b) {
    this.x = (b.l + b.r) / 2;
    this.y = b.t + 160;
    this.vx = this.vy = 0;
    this.spawned = true;
    this.mode = 'fall';
  }

  _drag(dt, env) {
    const nx = env.cursor.x - this.grabPt.gx + this.o.W / 2;
    const ny = env.cursor.y - this.grabPt.gy + this.o.row;
    this.hist.push({ t: this.t, x: nx, y: ny });
    while (this.hist.length > 2 && this.t - this.hist[0].t > 0.12) this.hist.shift();
    const ivx = dt > 0 ? (nx - this.x) / dt : 0;
    this.vx += (clamp(ivx, -2500, 2500) - this.vx) * 0.25;
    this.vy = 0;
    this.x = nx;
    this.y = ny;
  }

  _fall(dt, env) {
    const prevY = this.y;
    this.vy = Math.min(this.vy + this.o.gravity * dt, this.o.maxFall);
    if (this.mode !== 'jump') this.vx *= Math.max(0, 1 - 1.2 * dt); // a jump keeps its planned speed
    this.x += this.vx * dt;
    this.y += this.vy * dt;

    const lo = env.bounds.l + 60;
    const hi = env.bounds.r - 60;
    if (this.x < lo) {
      this.x = lo;
      this.vx = Math.abs(this.vx) * 0.4;
    } else if (this.x > hi) {
      this.x = hi;
      this.vx = -Math.abs(this.vx) * 0.4;
    }

    if (this.vy >= 0) {
      let hit = null;
      for (const s of env.surfaces) {
        if (this.mode === 'jump' && s.id === this.jumpFrom) continue; // do not land back where we left
        const inside = s.vis.some(([a, b]) => this.x >= a + 8 && this.x <= b - 8);
        if (!inside) continue;
        let landed;
        if (s.floor) landed = this.y >= s.y && this.y <= s.y + 400; // dropped onto/below the taskbar: snap up
        else landed = prevY <= s.y && s.y <= this.y; // windows: only when crossing from above
        if (landed && (!hit || s.y < hit.y)) hit = s;
      }
      if (hit) {
        this._land(hit);
        return;
      }
    }
    if (this.y > env.bounds.b + 900) this.respawn(env.bounds);
  }

  _land(s) {
    this.landSpeed = this.vy;
    this.y = s.y;
    this.surfaceId = s.id;
    this.xRel = this.x - s.wl;
    this.vx = this.vy = 0;
    this.mode = 'idle';
    this.jumpFrom = null;
    this.landedAt = this.t;
    this.nextDecision = this.t + 1.2 + this.o.rng() * 2;
  }

  _startFall() {
    this.jumpFrom = null;
    this.mode = 'fall';
    this.surfaceId = null;
    this.vx = this.vy = 0;
  }

  _segAt(s, x) {
    for (const seg of s.vis) if (x >= seg[0] - 12 && x <= seg[1] + 12) return seg;
    return null;
  }

  _ground(dt, env) {
    const s = env.surfaces.find((e) => e.id === this.surfaceId);
    if (!s) return this._startFall();

    // ride the surface (it may be a window the user is dragging around)
    const width = s.wr - s.wl;
    const m = Math.min(this.o.margin, width / 2);
    this.xRel = clamp(this.xRel, m, Math.max(m, width - m));
    const tx = s.wl + this.xRel;
    const k = 1 - Math.exp(-this.o.rideRate * dt);
    const px = this.x;
    this.x += (tx - this.x) * k;
    this.y += (s.y - this.y) * k;
    if (Math.abs(tx - this.x) < 0.4) this.x = tx;
    if (Math.abs(s.y - this.y) < 0.4) this.y = s.y;
    this.vx = dt > 0 ? (this.x - px) / dt : 0;

    const seg = this._segAt(s, this.x);
    if (!seg) return this._startFall(); // got covered by another window / surface vanished

    // music: dance while it plays (and we are not in the middle of a conversation)
    if (this.music && !this.busy) {
      if (this.mode !== 'dance') {
        this.mode = 'dance';
        this.dance = this._pickDance();
        this.danceSwitchAt = this.t + 18 + this.o.rng() * 12;
      } else if (this.t >= this.danceSwitchAt) {
        this.dance = this._pickDance();
        this.danceSwitchAt = this.t + 18 + this.o.rng() * 12;
      }
      this.lastActivity = this.t; // dancing counts as being awake
      return;
    }
    if (this.mode === 'dance') this._set('idle');

    // nap / wake
    const idleFor = this.t - this.lastActivity;
    if (this.mode === 'sleep') {
      if (idleFor < 1) this._set('idle');
    } else if (idleFor > this.o.sleepAfter && !this.busy) {
      this._set('sleep');
    }

    if (this.mode === 'walk') {
      if (this.busy) {
        this._set('idle');
      } else {
        this.xRel += this.walkDir * this.o.walkSpeed * dt;
        this.facing = this.walkDir;
        const nx = s.wl + this.xRel;
        const lo = seg[0] + this.o.margin;
        const hi = seg[1] - this.o.margin;
        if (nx < lo || nx > hi) {
          this.walkDir *= -1;
          this.xRel = clamp(nx, lo, hi) - s.wl;
        }
        if (this.t >= this.walkUntil) this._set('idle');
      }
    } else if (this.t >= this.nextDecision && this.mode !== 'sleep') {
      this._decide(seg, env);
    }
  }

  _set(mode) {
    this.mode = mode;
    this.nextDecision = this.t + 4 + this.o.rng() * 8;
  }

  static get DANCES() {
    return ['hiphop', 'salsa', 'shuffle'];
  }

  _pickDance() {
    const all = Pet.DANCES.filter((d) => d !== this.dance);
    return all[Math.floor(this.o.rng() * all.length)];
  }

  // Plan a ballistic jump to another visible ledge. Returns true if it started one.
  _tryJump(env) {
    const o = this.o;
    const cands = [];
    for (const s of env.surfaces) {
      if (s.id === this.surfaceId) continue;
      for (const [a, b] of s.vis) {
        const lo = a + o.margin;
        const hi = b - o.margin;
        if (hi - lo < 40) continue;
        const near = clamp(this.x, lo, hi);
        const up = this.y - s.y; // > 0 means the target is higher
        if (Math.abs(near - this.x) > o.jumpReach) continue;
        if (up > o.jumpMaxUp || -up > o.jumpMaxDown) continue;
        cands.push({ s, lo, hi, near, up });
      }
    }
    if (!cands.length) return false;
    const c = cands[Math.floor(o.rng() * cands.length)];
    let tx = clamp(c.near + (o.rng() - 0.5) * Math.min(240, c.hi - c.lo), c.lo, c.hi);
    tx = clamp(tx, this.x - o.jumpReach, this.x + o.jumpReach);
    const g = o.gravity;
    const dy = c.s.y - this.y; // negative when going up
    const clear = 70; // how far above the target ledge the arc peaks
    const vy0 = -Math.sqrt(2 * g * (Math.max(0, -dy) + clear));
    const T = (-vy0 + Math.sqrt(vy0 * vy0 + 2 * g * dy)) / g;
    this.vx = (tx - this.x) / T;
    this.vy = vy0;
    this.facing = tx >= this.x ? 1 : -1;
    this.jumpFrom = this.surfaceId;
    this.surfaceId = null;
    this.mode = 'jump';
    this.activity();
    return true;
  }

  _decide(seg, env) {
    const r = this.o.rng();
    if ((this.mode === 'idle' || this.mode === 'sit') && !this.busy && r < this.o.jumpChance) {
      if (this._tryJump(env)) return;
    }
    const roomToWalk = seg[1] - seg[0] >= 2 * this.o.margin + 160;
    if (this.mode === 'idle') {
      if (r < 0.3) {
        this._set('sit');
        this.nextDecision = this.t + 10 + this.o.rng() * 18;
      } else if (r < 0.75 && roomToWalk && !this.busy) {
        this.walkDir = this.o.rng() < 0.5 ? -1 : 1;
        this.walkUntil = this.t + 2.5 + this.o.rng() * 4;
        this.mode = 'walk';
        this.facing = this.walkDir;
        this.nextDecision = this.walkUntil;
      } else {
        this.nextDecision = this.t + 4 + this.o.rng() * 8;
      }
    } else if (this.mode === 'sit') {
      if (r < 0.7) this._set('idle');
      else this.nextDecision = this.t + 5 + this.o.rng() * 8;
    }
  }

  /* ---------------- output ---------------- */

  state(cursor) {
    const ox = this.x - this.o.W / 2;
    const oy = this.y - this.o.row;
    return {
      mode: this.mode,
      dance: this.mode === 'dance' ? this.dance : null,
      facing: this.facing,
      vx: this.mode === 'walk' ? this.walkDir * this.o.walkSpeed : this.vx,
      vy: this.vy,
      grounded: this.surfaceId !== null,
      landedAgo: this.t - this.landedAt,
      landSpeed: this.landSpeed,
      cx: cursor.x - ox, // cursor position relative to the window's top-left
      cy: cursor.y - oy,
    };
  }

  windowOrigin() {
    return { x: this.x - this.o.W / 2, y: this.y - this.o.row };
  }
}

module.exports = { Pet };

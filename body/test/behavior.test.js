'use strict';
const assert = require('assert');
const { Pet } = require('../behavior');

const bounds = { l: 0, t: 0, r: 1920, b: 1080 };
const floor = { id: 'floor:0', wl: 0, wr: 1920, y: 1040, vis: [[0, 1920]], floor: true };
const mkwin = (id, wl, wr, y, vis) => ({ id, wl, wr, y, vis: vis || [[wl, wr]], floor: false });
const cursor = { x: 100, y: 100 };
function run(pet, secs, env, dt = 1 / 60) {
  for (let i = 0; i < secs / dt; i++) pet.update(dt, Object.assign({ cursor }, env));
}
let seed = 1;
const rng = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

// 1. spawns above, falls to the taskbar floor
let p = new Pet({ rng });
run(p, 3, { bounds, surfaces: [floor] });
assert.strictEqual(p.surfaceId, 'floor:0');
assert.strictEqual(Math.round(p.y), 1040);
assert.ok(['idle', 'sit', 'walk'].includes(p.mode), p.mode);
console.log('ok 1 lands on taskbar floor ->', p.mode);

// 2. lands on a window top edge when one is under the pet
p = new Pet({ rng });
const win = mkwin('w1', 500, 1400, 500);
run(p, 3, { bounds, surfaces: [win, floor] });
assert.strictEqual(p.surfaceId, 'w1');
assert.strictEqual(Math.round(p.y), 500);
console.log('ok 2 lands on window top edge');

// 3. rides a window that is being dragged sideways
const start = p.x;
let w = win;
for (let i = 0; i < 60; i++) { w = mkwin('w1', 500 + i * 5, 1400 + i * 5, 500); p.update(1 / 60, { cursor, bounds, surfaces: [w, floor] }); }
run(p, 1, { bounds, surfaces: [w, floor] });
assert.ok(p.x > start + 250, `x moved ${p.x - start}`);
assert.strictEqual(p.surfaceId, 'w1');
console.log('ok 3 rides window, moved', Math.round(p.x - start));

// 4. window closes -> pet falls to the floor
run(p, 3, { bounds, surfaces: [floor] });
assert.strictEqual(p.surfaceId, 'floor:0');
console.log('ok 4 window closed -> falls to taskbar');

// 5. window gets covered where the pet stands -> falls
p = new Pet({ rng });
run(p, 3, { bounds, surfaces: [mkwin('w2', 500, 1400, 500), floor] });
assert.strictEqual(p.surfaceId, 'w2');
const covered = mkwin('w2', 500, 1400, 500, [[500, p.x - 100], [p.x + 100, 1400]]);
run(p, 3, { bounds, surfaces: [covered, floor] });
assert.strictEqual(p.surfaceId, 'floor:0');
console.log('ok 5 covered by another window -> falls');

// 6. drag, throw, land
p = new Pet({ rng });
run(p, 3, { bounds, surfaces: [floor] });
p.grab(200, 300);
for (let i = 0; i < 30; i++) p.update(1 / 60, { cursor: { x: 800 + i * 10, y: 300 }, bounds, surfaces: [floor] });
assert.strictEqual(p.mode, 'drag');
p.release();
assert.ok(p.vx > 300, 'throw velocity ' + p.vx);
run(p, 3, { bounds, surfaces: [floor] });
assert.strictEqual(p.surfaceId, 'floor:0');
console.log('ok 6 drag + throw + land, vx was big');

// 7. dropped below the floor line snaps back up onto the taskbar
p = new Pet({ rng });
run(p, 3, { bounds, surfaces: [floor] });
p.grab(200, 300);
p.update(1 / 60, { cursor: { x: 900, y: 300 + 1060 - p.o.row + 40 + 300 - 300 }, bounds, surfaces: [floor] });
p.release();
run(p, 1, { bounds, surfaces: [floor] });
assert.strictEqual(p.surfaceId, 'floor:0');
console.log('ok 7 drop below taskbar line snaps onto it');

// 8. naps after sleepAfter, wakes on activity
p = new Pet({ rng, sleepAfter: 10 });
run(p, 3, { bounds, surfaces: [floor] });
run(p, 12, { bounds, surfaces: [floor] });
assert.strictEqual(p.mode, 'sleep');
p.activity();
run(p, 0.5, { bounds, surfaces: [floor] });
assert.notStrictEqual(p.mode, 'sleep');
console.log('ok 8 sleeps when idle, wakes on activity');

// 9. walking never leaves the ledge; busy voice loop stops it walking away
p = new Pet({ rng, sleepAfter: 1e9, jumpChance: 0 });
const ledge = mkwin('w3', 600, 1000, 500);
run(p, 3, { bounds, surfaces: [ledge, floor] });
assert.strictEqual(p.surfaceId, 'w3');
let minX = 1e9, maxX = -1e9, walked = false;
for (let i = 0; i < 60 * 600; i++) { p.update(1 / 60, { cursor, bounds, surfaces: [ledge, floor] }); minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); if (p.mode === 'walk') walked = true; }
assert.strictEqual(p.surfaceId, 'w3', 'still on ledge after 10 minutes');
assert.ok(walked && maxX - minX > 40, `walked=${walked} range ${minX}..${maxX}`);
assert.ok(minX >= 600 && maxX <= 1000, `range ${minX}..${maxX}`);
p.busy = true; run(p, 1, { bounds, surfaces: [ledge, floor] });
assert.notStrictEqual(p.mode, 'walk');
console.log('ok 9 stays on ledge', Math.round(minX), Math.round(maxX));

// 10. state() reports cursor relative to window
const st = p.state({ x: p.x, y: p.y - 100 });
assert.strictEqual(Math.round(st.cx), p.o.W / 2);
assert.strictEqual(Math.round(st.cy), p.o.row - 100);
console.log('ok 10 state() cursor mapping');


// 11. jumps up from the taskbar onto a nearby window and lands on it
p = new Pet({ rng });
const jledge = mkwin('w2', 600, 1300, 800);
run(p, 3, { bounds, surfaces: [jledge, floor] });
p.x = 760; p.y = 1040; p.surfaceId = 'floor:0'; p.xRel = 760; p.mode = 'idle';
p.jumpSoon();
p.update(1 / 60, { cursor, bounds, surfaces: [jledge, floor] });
assert.strictEqual(p.mode, 'jump');
run(p, 3, { bounds, surfaces: [jledge, floor] });
assert.strictEqual(p.surfaceId, 'w2', 'landed on ' + p.surfaceId);
assert.strictEqual(Math.round(p.y), 800);
console.log('ok 11 jumps from taskbar up onto a window');

// 12. jumps down from a window onto the taskbar, never back onto its own jledge
p = new Pet({ rng });
const high = mkwin('w3', 600, 1300, 500);
run(p, 3, { bounds, surfaces: [high, floor] });
p.x = 900; p.y = 500; p.surfaceId = 'w3'; p.xRel = 300; p.mode = 'idle';
p.jumpSoon();
const farWin = mkwin('w4', 1500, 1900, 500);
p.update(1 / 60, { cursor, bounds, surfaces: [high, farWin, floor] });
assert.strictEqual(p.mode, 'jump');
run(p, 3, { bounds, surfaces: [high, farWin, floor] });
assert.notStrictEqual(p.surfaceId, 'w3');
assert.ok(p.surfaceId, 'landed somewhere');
console.log('ok 12 jumped off w3 and landed on', p.surfaceId);

// 13. no jump when nothing is in reach
p = new Pet({ rng });
run(p, 3, { bounds, surfaces: [floor] });
p.jumpSoon();
p.update(1 / 60, { cursor, bounds, surfaces: [floor] });
assert.notStrictEqual(p.mode, 'jump');
console.log('ok 13 no jump without a target');

// 14. music makes it dance, silence stops it, talking pauses it
p = new Pet({ rng });
run(p, 3, { bounds, surfaces: [floor] });
p.setMusic(true);
run(p, 1, { bounds, surfaces: [floor] });
assert.strictEqual(p.mode, 'dance');
assert.ok(Pet.DANCES.includes(p.state(cursor).dance));
p.busy = true;
run(p, 1, { bounds, surfaces: [floor] });
assert.notStrictEqual(p.mode, 'dance');
p.busy = false;
run(p, 1, { bounds, surfaces: [floor] });
assert.strictEqual(p.mode, 'dance');
p.setMusic(false);
run(p, 1, { bounds, surfaces: [floor] });
assert.notStrictEqual(p.mode, 'dance');
console.log('ok 14 dances to music, pauses while talking, stops at silence');

// 15. music wakes it from a nap
p = new Pet({ rng });
run(p, 3, { bounds, surfaces: [floor] });
p.force('sleep');
run(p, 0.5, { bounds, surfaces: [floor] });
assert.strictEqual(p.mode, 'sleep');
p.setMusic(true);
run(p, 0.5, { bounds, surfaces: [floor] });
assert.strictEqual(p.mode, 'dance');
console.log('ok 15 music wakes it up');

console.log('ALL BEHAVIOUR TESTS PASSED');

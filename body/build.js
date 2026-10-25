// Bundles src/renderer.js (+ three, three-vrm) into one file so the renderer needs no module resolution.
const esbuild = require('esbuild');
const path = require('path');

esbuild.buildSync({
  entryPoints: [path.join(__dirname, 'src', 'renderer.js')],
  bundle: true,
  format: 'iife',
  target: 'chrome130',
  outfile: path.join(__dirname, 'dist', 'renderer.bundle.js'),
  minify: true,
  legalComments: 'none',
  logLevel: 'warning',
});
console.log('[body] renderer bundled');

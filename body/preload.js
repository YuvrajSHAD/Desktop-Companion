'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('petAPI', {
  getConfig: () => ipcRenderer.invoke('config'),
  getModel: () => ipcRenderer.invoke('model'),
  setIgnore: (v) => ipcRenderer.send('ignore', !!v),
  dragStart: (gx, gy) => ipcRenderer.send('drag-start', { gx, gy }),
  dragEnd: () => ipcRenderer.send('drag-end'),
  activity: () => ipcRenderer.send('activity'),
  contextMenu: () => ipcRenderer.send('context-menu'),
  toBrain: (msg) => ipcRenderer.send('to-brain', msg),
  ready: () => ipcRenderer.send('renderer-ready'),
  onPet: (fn) => ipcRenderer.on('pet', (_e, s) => fn(s)),
  onEvent: (fn) => ipcRenderer.on('evt', (_e, m) => fn(m)),
});

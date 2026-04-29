'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  fetchUsage: () => ipcRenderer.invoke('fetch-usage'),
  claudeLogin: () => ipcRenderer.invoke('claude-login'),
  getSettings: () => ipcRenderer.invoke('get-settings'),
  saveSettings: s => ipcRenderer.invoke('save-settings', s),
  openExternal: url => ipcRenderer.invoke('open-external', url),
  onPanelOpened: cb => {
    const handler = () => cb();
    ipcRenderer.on('panel-opened', handler);
    return () => ipcRenderer.removeListener('panel-opened', handler);
  },
  panelMouseEnter: () => ipcRenderer.send('panel-mouse-enter'),
  panelMouseLeave: () => ipcRenderer.send('panel-mouse-leave'),
});

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("overflowPopup", {
  openHistory: () => ipcRenderer.invoke("browser:overflowOpenHistory") as Promise<void>
});

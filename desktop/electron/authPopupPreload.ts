import { contextBridge, ipcRenderer } from "electron";

interface AuthUserPayload {
  id: string;
  email?: string | null;
  name?: string | null;
  image?: string | null;
  [key: string]: unknown;
}

interface AuthErrorPayload {
  message?: string;
  status: number;
  statusText: string;
  path: string;
}

interface RuntimeConfigPayload {
  configPath: string | null;
  loadedFromFile: boolean;
  authTokenPresent: boolean;
  userId: string | null;
  sandboxId: string | null;
  modelProxyBaseUrl: string | null;
  defaultModel: string | null;
  controlPlaneBaseUrl: string | null;
}

interface RuntimeConfigUpdatePayload {
  authToken?: string | null;
  modelProxyApiKey?: string | null;
  userId?: string | null;
  sandboxId?: string | null;
  modelProxyBaseUrl?: string | null;
  defaultModel?: string | null;
  controlPlaneBaseUrl?: string | null;
}

const CONTROL_PLANE_BASE_URL = (process.env.HOLABOSS_DESKTOP_CONTROL_PLANE_BASE_URL?.trim() || "http://127.0.0.1:3060").replace(
  /\/+$/,
  ""
);
const DEFAULT_MODEL_PROXY_BASE_URL = `${CONTROL_PLANE_BASE_URL}/api/v1/model-proxy`;
const DEFAULT_RUNTIME_MODEL = "openai/gpt-5.1";

contextBridge.exposeInMainWorld("authPopup", {
  getDefaults: () => ({
    modelProxyBaseUrl: DEFAULT_MODEL_PROXY_BASE_URL,
    defaultModel: DEFAULT_RUNTIME_MODEL
  }),
  getUser: () => ipcRenderer.invoke("auth:getUser") as Promise<AuthUserPayload | null>,
  requestAuth: () => ipcRenderer.invoke("auth:requestAuth") as Promise<void>,
  signOut: () => ipcRenderer.invoke("auth:signOut") as Promise<void>,
  getRuntimeConfig: () => ipcRenderer.invoke("runtime:getConfig") as Promise<RuntimeConfigPayload>,
  setRuntimeConfig: (payload: RuntimeConfigUpdatePayload) =>
    ipcRenderer.invoke("runtime:setConfig", payload) as Promise<RuntimeConfigPayload>,
  exchangeBinding: (sandboxId: string) => ipcRenderer.invoke("runtime:exchangeBinding", sandboxId) as Promise<RuntimeConfigPayload>,
  close: () => ipcRenderer.invoke("auth:closePopup") as Promise<void>,
  onAuthenticated: (listener: (user: AuthUserPayload) => void) => {
    const wrapped = (_event: Electron.IpcRendererEvent, user: AuthUserPayload) => listener(user);
    ipcRenderer.on("auth:authenticated", wrapped);
    return () => ipcRenderer.removeListener("auth:authenticated", wrapped);
  },
  onUserUpdated: (listener: (user: AuthUserPayload | null) => void) => {
    const wrapped = (_event: Electron.IpcRendererEvent, user: AuthUserPayload | null) => listener(user);
    ipcRenderer.on("auth:userUpdated", wrapped);
    return () => ipcRenderer.removeListener("auth:userUpdated", wrapped);
  },
  onError: (listener: (payload: AuthErrorPayload) => void) => {
    const wrapped = (_event: Electron.IpcRendererEvent, payload: AuthErrorPayload) => listener(payload);
    ipcRenderer.on("auth:error", wrapped);
    return () => ipcRenderer.removeListener("auth:error", wrapped);
  }
});

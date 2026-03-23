# Holaboss Local - Neon AI Workspace Prototype

Desktop prototype inspired by a futuristic dark neon-green AI operating workspace with three docked panes:

1. File Explorer (left)
2. In-app Browser panel (center)
3. AI Chat assistant (right)

Built with Electron + React + TypeScript + Vite + Tailwind CSS.

## Features

- Electron main/preload/renderer separation with secure preload bridge
- Full-window dark neon-green visual system
- Global top tab bar with workspace controls
- Three-pane layout with draggable split handles
- Pane widths persist in local storage
- Real local file explorer (reads your filesystem via secure IPC)
- Real embedded Chromium browser (`<webview>`) with URL/home/back/forward/refresh
- AI chat panel with suggestion pills, composer, user/assistant bubbles, and local rule-based responses

## Tech Stack

- Electron
- React 19
- TypeScript
- Vite
- Tailwind CSS
- Lucide React icons

## Run

```bash
npm install
GITHUB_TOKEN="$(gh auth token)" npm run prepare:runtime
npm run dev
```

This launches:
- Vite dev server for the renderer (`http://localhost:5173`)
- TS build watcher for Electron main/preload (`../out/desktop/dist-electron/*.cjs`)
- Electron desktop window with live restarts on main/preload changes

Control-plane endpoint presets:

```bash
# local control plane/services (127.0.0.1:3060/3033/3037)
npm run dev:cp:local

# dev control plane (54.214.105.154:3060)
npm run dev:cp:dev

# prod control plane (35.160.37.189:3060)
npm run dev:cp:prod
```

`prepare:runtime` downloads the pinned macOS runtime bundle from the GitHub release defined in [runtime-manifest.json](/Users/jeffrey/Desktop/hola-boss-oss/desktop/runtime-manifest.json) and stages it into `../out/desktop/runtime-macos/`.

## Build

```bash
npm run build
```

This creates:
- Renderer production bundle in `../out/desktop/dist/`
- Electron main/preload bundles in `../out/desktop/dist-electron/`

## Runtime Bundle

Production mac builds expect a staged runtime bundle at `../out/desktop/runtime-macos/`. You can stage it with:

```bash
npm run prepare:runtime
```

For local development against unreleased `hola-boss-oss` runtime changes:

```bash
# optional when your OSS repo is not ../hola-boss-oss
export HOLABOSS_OSS_ROOT=/absolute/path/to/hola-boss-oss

# builds runtime bundle from local hola-boss-oss and stages it into ../out/desktop/runtime-macos
npm run prepare:runtime:local
```

Or package directly with local runtime in one step:

```bash
npm run dist:mac:local
```

The staging script accepts one of:
- `HOLABOSS_RUNTIME_DIR=/absolute/path/to/runtime-macos`
- `HOLABOSS_RUNTIME_TARBALL=/absolute/path/to/holaboss-runtime-macos-<sha>.tar.gz`
- `HOLABOSS_RUNTIME_BUNDLE_URL=https://.../holaboss-runtime-macos-<sha>.tar.gz`
- `HOLABOSS_GITHUB_TOKEN=...` or `GITHUB_TOKEN=...` to fetch the pinned asset from GitHub Releases using [runtime-manifest.json](/Users/jeffrey/Desktop/hola-boss-oss/desktop/runtime-manifest.json)

If none are set, it falls back to `/tmp/holaboss-runtime-macos-full` when present.

To build a mac app bundle with the runtime embedded in Electron resources:

```bash
GITHUB_TOKEN="$(gh auth token)" npm run dist:mac
```

Use `dist:mac` when you intentionally want the runtime pinned in [runtime-manifest.json](/Users/jeffrey/Desktop/hola-boss-oss/desktop/runtime-manifest.json) from GitHub releases. Use `dist:mac:local` for local unreleased runtime code.

This produces an unsigned local mac app bundle with `runtime-macos` embedded in `Contents/Resources/`.

Output:
- [Holaboss Workspace.app](/Users/jeffrey/Desktop/hola-boss-oss/out/desktop/release/mac-arm64/Holaboss%20Workspace.app)

Run packaged app with endpoint presets:

```bash
# uses ../out/desktop/release/mac-arm64/... by default
npm run packaged:run:local
npm run packaged:run:dev
npm run packaged:run:prod
```

Optional overrides:
- `HOLABOSS_AUTH_BASE_URL` for Better Auth session endpoint
- `HOLABOSS_DESKTOP_CONTROL_PLANE_BASE_URL` for desktop binding/control-plane endpoint
- `HOLABOSS_PROJECTS_URL` for projects service endpoint (default derived from control-plane host + `:3033`)
- `HOLABOSS_MARKETPLACE_URL` for marketplace service endpoint (default derived from control-plane host + `:3037`)
- `HOLABOSS_PACKAGED_APP_BIN` for an explicit packaged binary path

To build a mac installer image:

```bash
GITHUB_TOKEN="$(gh auth token)" npm run dist:mac:dmg
```

This produces an unsigned `.dmg` installer in `../out/desktop/release/`.

Notes:
- `dist:mac` builds an unpacked `.app`
- `dist:mac:dmg` builds a `.dmg` installer
- both local mac packaging commands are intentionally unsigned because they pass `--config.mac.identity=null`
- for production distribution, signing and notarization still need to be added

## Project Structure

```text
electron/
  main.ts
  preload.ts
src/
  components/
    layout/
      AppShell.tsx
      TopTabsBar.tsx
      SplitPaneLayout.tsx
    panes/
      FileExplorerPane.tsx
      BrowserPane.tsx
      ChatPane.tsx
    ui/
      PaneCard.tsx
      IconButton.tsx
  data/
    mockFiles.ts
    mockBrowser.ts
  utils/
    mockAssistant.ts
  types/
    electron.d.ts
    webview.d.ts
  App.tsx
  main.tsx
  index.css
```

## Browser Notes

The center pane uses a real Electron `webview`:
- Source is set in `src/components/panes/BrowserPane.tsx`
- Navigation controls call real webview methods (`goBack`, `goForward`, `reload`, `loadURL`)
- Main process enables and guards webview attachment in `electron/main.ts`

If you later want a multi-tab browser architecture, keep the current `BrowserPane` control surface and swap to a tab manager that creates one webview per tab.

## File Explorer Notes

The left pane reads real directories from your machine:
- IPC handler lives in `electron/main.ts` (`fs:listDirectory`)
- Renderer call lives in preload bridge (`window.electronAPI.fs.listDirectory`)
- UI and navigation are in `src/components/panes/FileExplorerPane.tsx`

The explorer currently supports:
- folder open (double-click or “Open Selected Folder”)
- back/forward/up/home navigation
- search/filter in current directory
- grouped rendering by modified date (Today / This Week / This Year / Earlier)

### AI assistant

Current chat replies are local rule-based mocks (no backend/LLM):
- Rules and canned responses live in `src/utils/mockAssistant.ts`
- `ChatPane.tsx` handles message rendering and send flow

Replace point for real AI backend:
- Hook send flow in `src/components/panes/ChatPane.tsx` where `generateMockReply` is called
- Replace timeout mock with API call and stream/append tokens as needed

## Security

Renderer runs with:
- `contextIsolation: true`
- `nodeIntegration: false`
- `webviewTag: true` (enabled intentionally for embedded browser pane)

Preload bridge exposes runtime info and a constrained filesystem API via `window.electronAPI`.

## Stretch Goals Ready

Codebase is structured to support later additions such as:
- draggable top tabs
- command palette
- collapsible icon rail
- tokenized theme switching

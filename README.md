# Hola Boss OSS

This repo now contains both the local desktop app and the runtime it embeds.

## Layout

- `desktop/`: Electron + React desktop app
- `runtime/`: Python runtime package, tests, and packaging scripts
- `.github/workflows/`: CI and publishing workflows

## Prerequisites

- Node.js 22+
- npm
- Python 3.12
- `uv`

## Quick Start

Install desktop dependencies:

```bash
npm run desktop:install
```

Build and stage a local runtime bundle from this repo into `desktop/out/runtime-macos`:

```bash
npm run desktop:prepare-runtime:local
```

Run the desktop app in development:

```bash
npm run desktop:dev
```

This starts:

- the Vite renderer dev server
- the Electron main/preload watcher
- the Electron app itself

## Common Commands

Run the desktop typecheck:

```bash
npm run desktop:typecheck
```

Run runtime tests:

```bash
npm run runtime:test
```

Build a local macOS desktop bundle with the locally built runtime embedded:

```bash
npm run desktop:dist:mac:local
```

Stage the runtime from the pinned desktop manifest instead of building it locally:

```bash
npm run desktop:prepare-runtime
```

## Development Notes

The root `package.json` is just a thin command wrapper for the desktop app. The actual desktop project still lives in `desktop/package.json`.

`runtime/` remains independently buildable and testable. The desktop app consumes its packaged output rather than importing Python source files directly.

For local desktop work, the default flow is:

```bash
npm run desktop:install
npm run desktop:prepare-runtime:local
npm run desktop:dev
```

For runtime-only work, the main command is:

```bash
npm run runtime:test
```

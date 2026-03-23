import { useEffect, useMemo, useRef, useState } from "react";
import { TopTabsBar } from "@/components/layout/TopTabsBar";
import { SplitPaneLayout } from "@/components/layout/SplitPaneLayout";
import { BrowserPane } from "@/components/panes/BrowserPane";
import { ChatPane } from "@/components/panes/ChatPane";
import { FileExplorerPane } from "@/components/panes/FileExplorerPane";
import { WorkspaceDesktopProvider } from "@/lib/workspaceDesktop";
import { WorkspaceSelectionProvider } from "@/lib/workspaceSelection";

const STORAGE_KEY = "holaboss-pane-sizes-v1";
const THEME_STORAGE_KEY = "holaboss-theme-v1";
const DEFAULT_SIZES: [number, number, number] = [32, 38, 30];
const THEMES = ["emerald", "cobalt", "ember", "glacier", "mono", "claude", "slate", "paper", "graphite"] as const;
export type AppTheme = (typeof THEMES)[number];

function loadSizes(): [number, number, number] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return DEFAULT_SIZES;
    }

    const parsed = JSON.parse(raw) as number[];
    if (parsed.length !== 3) {
      return DEFAULT_SIZES;
    }

    const total = parsed.reduce((sum, value) => sum + value, 0);
    if (total < 99 || total > 101) {
      return DEFAULT_SIZES;
    }

    return [parsed[0], parsed[1], parsed[2]];
  } catch {
    return DEFAULT_SIZES;
  }
}

function loadTheme(): AppTheme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored && THEMES.includes(stored as AppTheme)) {
      return stored as AppTheme;
    }
  } catch {
    // ignore
  }

  return "emerald";
}

export function AppShell() {
  const [sizes, setSizes] = useState<[number, number, number]>(loadSizes);
  const [theme, setTheme] = useState<AppTheme>(loadTheme);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatusPayload | null>(null);
  const userMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!window.electronAPI) {
      return;
    }

    let mounted = true;
    void window.electronAPI.runtime.getStatus().then((status) => {
      if (mounted) {
        setRuntimeStatus(status);
      }
    });

    const unsubscribe = window.electronAPI.runtime.onStateChange((status) => {
      if (mounted) {
        setRuntimeStatus(status);
      }
    });

    return () => {
      mounted = false;
      unsubscribe();
    };
  }, []);

  const runtimeInfo = useMemo(() => {
    if (!window.electronAPI) {
      return {
        label: "Web",
        detail: "Web runtime"
      };
    }

    const platformInfo = `${window.electronAPI.platform.toUpperCase()} - ELECTRON ${window.electronAPI.versions.electron}`;
    if (!runtimeStatus) {
      return {
        label: "Unknown",
        detail: `${platformInfo} - runtime unknown`
      };
    }

    const statusLabelByState: Record<RuntimeStatusPayload["status"], string> = {
      disabled: "Runtime disabled",
      missing: "Runtime missing",
      starting: "Runtime starting",
      running: "Runtime running",
      stopped: "Runtime stopped",
      error: "Runtime error"
    };

      return {
      label:
        runtimeStatus.status === "running"
          ? "Running"
          : runtimeStatus.status === "starting"
            ? "Starting"
            : runtimeStatus.status === "error"
              ? "Error"
              : runtimeStatus.status === "missing"
                ? "Missing"
                : runtimeStatus.status === "disabled"
                  ? "Disabled"
                : "Stopped",
      detail: `${platformInfo} - ${statusLabelByState[runtimeStatus.status]}`
    };
  }, [runtimeStatus]);

  const handleSizesChange = (nextSizes: [number, number, number]) => {
    setSizes(nextSizes);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(nextSizes.map((size) => Number(size.toFixed(2)))));
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_STORAGE_KEY, theme);
    void window.electronAPI.ui.setTheme(theme);
  }, [theme]);

  return (
    <main className="fixed inset-0 overflow-hidden text-[13px] text-text-main/90">
      <div className="theme-grid pointer-events-none absolute inset-0 bg-noise-grid bg-[size:22px_22px]" />
      <div className="theme-orb-primary pointer-events-none absolute -left-32 -top-32 h-80 w-80 rounded-full blur-3xl" />
      <div className="theme-orb-secondary pointer-events-none absolute -bottom-40 right-12 h-96 w-96 rounded-full blur-3xl" />

      <div className="relative z-10 grid h-full w-full grid-rows-[auto_minmax(0,1fr)] gap-2 p-2 sm:gap-3 sm:p-3">
        <WorkspaceSelectionProvider>
          <WorkspaceDesktopProvider>
            <div className="relative flex min-w-0 items-center justify-between gap-2 sm:gap-3">
              <div ref={userMenuRef} className="relative min-w-0 flex-1">
                <TopTabsBar
                  theme={theme}
                  onThemeChange={setTheme}
                  onUserMenuToggle={(anchorBounds) => {
                    void window.electronAPI.auth.togglePopup(anchorBounds);
                  }}
                  runtimeIndicator={{
                    label: runtimeInfo.label,
                    detail: runtimeInfo.detail,
                    status: runtimeStatus?.status ?? null
                  }}
                />
              </div>
            </div>

            <div className="relative min-h-0 overflow-hidden">
              <SplitPaneLayout
                sizes={sizes}
                onSizesChange={handleSizesChange}
                left={<FileExplorerPane />}
                center={<BrowserPane />}
                right={<ChatPane />}
              />
            </div>
          </WorkspaceDesktopProvider>
        </WorkspaceSelectionProvider>
      </div>
    </main>
  );
}

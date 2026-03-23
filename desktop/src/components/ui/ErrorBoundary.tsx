import { Component, ErrorInfo, ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
    message: ""
  };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      message: error.message || "Unknown renderer error"
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <main className="flex h-full w-full items-center justify-center bg-obsidian p-6 text-text-main">
        <div className="max-w-xl rounded-xl border border-neon-green/40 bg-obsidian-soft/90 p-5 shadow-glow">
          <h1 className="mb-2 text-lg font-semibold text-neon-green">Renderer Error</h1>
          <p className="text-sm text-text-muted/85">
            A component crashed. Check terminal logs for the stack trace and restart the app.
          </p>
          <pre className="mt-3 overflow-auto rounded-lg border border-neon-green/20 bg-black/40 p-3 text-xs text-text-main/80">
            {this.state.message}
          </pre>
        </div>
      </main>
    );
  }
}

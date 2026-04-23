import React from "react";
import { AlertCircle, RefreshCw } from "lucide-react";

/**
 * ErrorBoundary: wraps a child subtree and renders a friendly fallback
 * whenever the subtree throws. The `resetKey` prop allows the parent to force
 * the boundary to reset (e.g. when the user changes a filter/period).
 *
 * Usage:
 *   <ErrorBoundary resetKey={period} label="Medalists view">
 *     <MedalistsView ... />
 *   </ErrorBoundary>
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Surface in dev console; in prod this could post to a logger.
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", this.props.label || "", error, info);
  }

  componentDidUpdate(prev) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;

    const msg = this.state.error?.message || String(this.state.error);
    return (
      <div className="border border-amber-300 bg-amber-50 rounded-lg p-4 my-3" data-testid="outreach-error-boundary">
        <div className="flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-amber-900">
              Couldn't render {this.props.label || "this view"}.
            </p>
            <p className="text-xs text-amber-800 mt-1">
              The data for this period may contain an unexpected shape. Try a different period, or reload the page.
            </p>
            <pre className="text-[10px] text-amber-800/80 mt-2 whitespace-pre-wrap break-words max-h-24 overflow-auto">
              {msg}
            </pre>
            <button
              onClick={() => { this.setState({ error: null }); window.location.reload(); }}
              className="mt-3 inline-flex items-center gap-1 text-xs px-2 py-1 rounded border border-amber-600 text-amber-700 hover:bg-amber-600 hover:text-white transition-colors"
              data-testid="outreach-error-reload"
            >
              <RefreshCw className="h-3 w-3" /> Reload
            </button>
          </div>
        </div>
      </div>
    );
  }
}

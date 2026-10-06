import { Component, type ErrorInfo, type ReactNode } from 'react';

interface State {
  error: Error | null;
}

/** Last-resort boundary: a calm message instead of a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Legal Lens crashed', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        role="alert"
        style={{
          display: 'grid',
          placeItems: 'center',
          height: '100%',
          padding: 24,
          textAlign: 'center',
        }}
      >
        <div style={{ maxWidth: 420 }}>
          <h1 style={{ fontFamily: 'var(--font-serif)', fontSize: 'var(--text-2xl)', marginBottom: 8 }}>
            Something went wrong
          </h1>
          <p style={{ color: 'var(--text-muted)', marginBottom: 20 }}>
            Legal Lens hit an unexpected error. Your documents and conversations are safe on this
            device. Reload to continue.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              height: 36,
              padding: '0 16px',
              border: 0,
              borderRadius: 'var(--radius)',
              background: 'var(--primary)',
              color: '#fff',
              fontWeight: 550,
            }}
          >
            Reload Legal Lens
          </button>
        </div>
      </div>
    );
  }
}

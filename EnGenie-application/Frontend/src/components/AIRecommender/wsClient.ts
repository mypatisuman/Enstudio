// wsClient.ts — WebSocket client for bidirectional job streaming.
//
// Drop-in replacement for sseClient's streamJobEvents: same signature, same
// {type, data} event envelope, so consumers only swap the import path.
//
// Auth: the browser WebSocket API can't set headers, so the JWT is passed as a
// `?token=` query param. Use wss:// in production (TLS) so it isn't exposed.

/** Build the ws(s):// base URL. Dev → same-origin (Vite proxy); prod → backend. */
function wsBase(): string {
  if (import.meta.env.DEV) {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    return `${scheme}://${location.host}`; // proxied by Vite (server.proxy ws:true)
  }
  const backend = import.meta.env.VITE_BACKEND_URL || "https://api.engenieai.com";
  return backend.replace(/^http/, "ws"); // http→ws, https→wss
}

export interface StreamOptions {
  /** Called for every server event with its type and parsed payload. */
  onEvent?: (type: string, data: any) => void;
  /** Overall timeout in ms before the socket is closed. Default 30 min. */
  timeoutMs?: number;
  /** External abort signal (e.g. React cleanup) to close the socket. */
  signal?: AbortSignal;
}

/**
 * Open a WebSocket stream for a job and invoke `onEvent` for each pushed event.
 *
 * Resolves when the server ends the stream (a `close`, `result`, or `error`
 * event, or the socket closing). Rejects on socket error or timeout
 * (a `TimeoutError` DOMException). `ping` heartbeats are swallowed.
 *
 * The returned promise also exposes `.socket` so callers can send commands
 * back to the server (e.g. cancel) over the same connection.
 */
// Overall stream ceiling. Deep vendor analysis on heavy/slow models can run
// long, so allow ops to raise it via VITE_WS_TIMEOUT_MS (default 30 min).
const DEFAULT_WS_TIMEOUT_MS = Number(import.meta.env.VITE_WS_TIMEOUT_MS) || 1800000;

export function streamJobEvents(streamId: string, opts: StreamOptions = {}): Promise<void> & { socket: WebSocket } {
  const { onEvent, timeoutMs = DEFAULT_WS_TIMEOUT_MS, signal } = opts;

  const token = localStorage.getItem("auth_token") || "";
  const url = `${wsBase()}/api/ws/${streamId}?token=${encodeURIComponent(token)}`;
  const socket = new WebSocket(url);

  let settled = false;
  let timer: ReturnType<typeof setTimeout>;

  const promise = new Promise<void>((resolve, reject) => {
    const closeSocket = () => {
      // Closing a socket that's still CONNECTING logs a noisy
      // "WebSocket is closed before the connection is established" warning.
      // This happens when a short-lived consumer (e.g. the StreamingProgress
      // animation) unmounts before the handshake to a remote server finishes.
      // Defer the close until it opens so the teardown is clean.
      if (socket.readyState === WebSocket.CONNECTING) {
        socket.onmessage = null; // ignore anything that arrives in the meantime
        socket.onopen = () => { try { socket.close(); } catch { /* noop */ } };
      } else {
        try { socket.close(); } catch { /* already closing */ }
      }
    };

    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", onAbort);
      closeSocket();
      fn();
    };

    function onAbort() {
      finish(() => reject(new DOMException("Aborted", "AbortError")));
    }

    timer = setTimeout(
      () => finish(() => reject(new DOMException("Stream timed out", "TimeoutError"))),
      timeoutMs
    );

    if (signal) {
      if (signal.aborted) { onAbort(); return; }
      signal.addEventListener("abort", onAbort);
    }

    socket.onmessage = (e) => {
      let msg: { type: string; data: any };
      try {
        msg = JSON.parse(e.data);
      } catch {
        return;
      }
      if (msg.type === "ping") return; // heartbeat
      onEvent?.(msg.type, msg.data ?? {});
      if (msg.type === "result" || msg.type === "error" || msg.type === "close") {
        finish(resolve);
      }
    };

    socket.onerror = () => finish(() => reject(new Error("WebSocket connection error")));
    socket.onclose = () => finish(resolve); // server ended the stream
  });

  return Object.assign(promise, { socket });
}

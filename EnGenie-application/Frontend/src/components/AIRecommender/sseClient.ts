// sseClient.ts — fetch-based Server-Sent Events client.
//
// Native EventSource cannot send custom headers, but this app authenticates
// with a JWT in the `Authorization` header. So we consume SSE via fetch +
// ReadableStream, which lets us attach the bearer token. Dependency-free.

const BASE_URL: string = import.meta.env.DEV
  ? "" // Vite proxy in dev (same-origin)
  : (import.meta.env.VITE_BACKEND_URL || "https://api.engenieai.com");

export interface StreamOptions {
  /** Called for every server event with its type and parsed JSON payload. */
  onEvent?: (type: string, data: any) => void;
  /** Overall timeout in ms before the stream is aborted. Default 30 min. */
  timeoutMs?: number;
  /** External abort signal (e.g. React cleanup) to cancel the stream. */
  signal?: AbortSignal;
}

/**
 * Open an SSE stream for a job and invoke `onEvent` for each pushed event.
 *
 * Resolves when the server closes the stream (a `close`, `result`, or `error`
 * event, or the connection ending). Rejects on network failure, a non-OK
 * response, or timeout (a `TimeoutError` DOMException). Aborting via `signal`
 * rejects with an `AbortError`.
 */
export async function streamJobEvents(
  streamId: string,
  opts: StreamOptions = {}
): Promise<void> {
  const { onEvent, timeoutMs = 1800000, signal } = opts;

  const controller = new AbortController();
  const onExternalAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", onExternalAbort);
  }
  const timer = setTimeout(
    () => controller.abort(new DOMException("Stream timed out", "TimeoutError")),
    timeoutMs
  );

  try {
    const token = localStorage.getItem("auth_token");
    const response = await fetch(`${BASE_URL}/api/events/${streamId}`, {
      method: "GET",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        Accept: "text/event-stream",
      },
      credentials: "include",
      signal: controller.signal,
    });

    if (!response.ok || !response.body) {
      throw new Error(`SSE connection failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line.
      let sepIndex: number;
      while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);

        const parsed = parseFrame(frame);
        if (parsed.event === null) continue; // comment / heartbeat

        let payload: any = {};
        try {
          payload = parsed.data ? JSON.parse(parsed.data) : {};
        } catch {
          payload = parsed.data;
        }
        onEvent?.(parsed.event, payload);
      }
    }
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener("abort", onExternalAbort);
  }
}

/** Parse a single SSE frame into its event name and data. Returns event=null for comments. */
function parseFrame(frame: string): { event: string | null; data: string } {
  let event = "message";
  const dataLines: string[] = [];
  let hasField = false;

  for (const line of frame.split("\n")) {
    if (line === "" || line.startsWith(":")) continue; // comment / blank
    hasField = true;
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }

  if (!hasField) return { event: null, data: "" };
  return { event, data: dataLines.join("\n") };
}

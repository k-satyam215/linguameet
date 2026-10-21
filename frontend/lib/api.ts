export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Lang = {
  code: string;
  name: string;
  base: string;
  bcp47: string;
  asr: boolean;
  translate: boolean;
  tts: boolean;
};

export type JoinInfo = {
  identity: string;
  livekit_url: string;
  livekit_token: string;
  ws_token: string;
};

// Used when the API is unreachable so the lobby still renders.
export const FALLBACK_LANGS: Lang[] = [
  { code: "en", name: "English", base: "en", bcp47: "en-US", asr: true, translate: true, tts: true },
  { code: "hi", name: "Hindi", base: "hi", bcp47: "hi-IN", asr: true, translate: true, tts: true },
  { code: "hi-en", name: "Hinglish", base: "hi", bcp47: "hi-IN", asr: true, translate: true, tts: true },
];

export async function fetchLanguages(): Promise<Lang[]> {
  try {
    const r = await fetch(`${API_URL}/api/languages`, { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    return (await r.json()).languages as Lang[];
  } catch {
    return FALLBACK_LANGS;
  }
}

export async function joinRoom(p: { room: string; name: string; speak: string; listen: string }): Promise<JoinInfo> {
  const r = await fetch(`${API_URL}/api/join`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(p),
  });
  if (!r.ok) {
    let msg = `Join failed (${r.status})`;
    try {
      const j = await r.json();
      if (typeof j.detail === "string") msg = j.detail;
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export function wsUrl(token: string): string {
  const base = API_URL.replace(/^http/, "ws");
  return `${base}/ws/translate?token=${encodeURIComponent(token)}`;
}

export function randomRoom(): string {
  const a = "abcdefghjkmnpqrstuvwxyz23456789";
  const pick = (n: number) =>
    Array.from({ length: n }, () => a[Math.floor(Math.random() * a.length)]).join("");
  return `${pick(3)}-${pick(4)}-${pick(3)}`;
}

export function validRoom(code: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9_-]{2,39}$/.test(code);
}

export class TtsError extends Error {
  constructor(public status: number, public retryAfter: number) {
    super(`voice failed (${status})`);
  }
}

// Natural voice for one translated sentence. Rejects with TtsError so callers can fall back.
export async function fetchTts(token: string, text: string, speaker: string, timeoutMs = 8000): Promise<Blob> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`${API_URL}/api/tts`, {
      method: "POST",
      headers: { "content-type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ text, speaker }),
      signal: ctrl.signal,
    });
    if (!r.ok) throw new TtsError(r.status, Number(r.headers.get("retry-after")) || 0);
    return await r.blob();
  } catch (e) {
    if (e instanceof TtsError) throw e;
    throw new TtsError(0, 0); // network error or timeout
  } finally {
    clearTimeout(timer);
  }
}

export async function hostAction(
  token: string,
  action: "mute" | "remove" | "lock",
  body: { target?: string; locked?: boolean }
): Promise<unknown> {
  const r = await fetch(`${API_URL}/api/host/${action}`, {
    method: "POST",
    headers: { "content-type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = `Action failed (${r.status})`;
    try {
      const j = await r.json();
      if (typeof j.detail === "string") msg = j.detail;
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

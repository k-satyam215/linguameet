// Chat + reactions travel over LiveKit data channels. Sender identity comes from LiveKit
// (authenticated), never from the payload. Everything received is validated and rendered as text.

export const EMOJIS = ["👍", "👏", "❤️", "😂", "🎉", "😮"] as const;
export const MAX_CHAT = 500;

export type ChatMsg = { id: string; from: string; name: string; text: string; at: number };
export type Reaction = { kind: "hand"; on: boolean } | { kind: "emoji"; emoji: string };

const enc = new TextEncoder();
export const encode = (obj: unknown): Uint8Array => enc.encode(JSON.stringify(obj));

function parse(raw: string): Record<string, unknown> | null {
  try {
    const v = JSON.parse(raw);
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export function parseChat(raw: string): string | null {
  const o = parse(raw);
  if (!o || typeof o.text !== "string") return null;
  const t = o.text.trim().slice(0, MAX_CHAT);
  return t || null;
}

export function parseReaction(raw: string): Reaction | null {
  const o = parse(raw);
  if (!o) return null;
  if (typeof o.hand === "boolean") return { kind: "hand", on: o.hand };
  if (typeof o.emoji === "string" && (EMOJIS as readonly string[]).includes(o.emoji)) return { kind: "emoji", emoji: o.emoji };
  return null;
}

export function uid(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
}

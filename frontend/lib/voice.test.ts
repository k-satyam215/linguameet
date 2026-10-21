import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceQueue } from "./voice";

const flush = (ms = 20) => new Promise((r) => setTimeout(r, ms));

class FakeAudio {
  static played: string[] = [];
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public src: string) {}
  play() {
    FakeAudio.played.push(this.src);
    setTimeout(() => this.onended?.(), 1);
    return Promise.resolve();
  }
  pause() {}
}

let fetchImpl: (body: { text: string }) => Promise<Response>;

beforeEach(() => {
  FakeAudio.played = [];
  vi.stubGlobal("Audio", FakeAudio);
  vi.stubGlobal("URL", { createObjectURL: (b: Blob) => `blob:${(b as any).tag}`, revokeObjectURL: () => {} });
  vi.stubGlobal("fetch", (_u: string, init: { body: string }) => fetchImpl(JSON.parse(init.body)));
});
afterEach(() => vi.unstubAllGlobals());

const ok = (tag: string, delay = 0) =>
  new Promise<Response>((res) => setTimeout(() => res({ ok: true, status: 200, blob: async () => Object.assign(new Blob(["x"]), { tag }), headers: new Headers() } as unknown as Response), delay));
const fail = (status: number, retry = "") =>
  Promise.resolve({ ok: false, status, headers: new Headers(retry ? { "retry-after": retry } : {}) } as unknown as Response);

const q = (server = true) => new VoiceQueue({ getToken: () => "tok", serverTts: () => server });
const opts = (extra: object = {}) => ({ speakerId: "u1", lang: "hi-IN", ...extra });

describe("VoiceQueue", () => {
  it("plays sentences in order even when a later one is synthesized first", async () => {
    fetchImpl = ({ text }) => ok(text, text === "one" ? 40 : 1);
    const v = q();
    v.speak("one", opts());
    v.speak("two", opts());
    await flush(120);
    expect(FakeAudio.played).toEqual(["blob:one", "blob:two"]);
    expect(v.busy).toBe(false);
  });

  it("fires onStart/onEnd and is not busy inside the last onEnd (mic unpause logic relies on this)", async () => {
    fetchImpl = ({ text }) => ok(text);
    const v = q();
    const events: string[] = [];
    let busyAtEnd: boolean | null = null;
    v.speak("hello", opts({ onStart: () => events.push("start"), onEnd: () => { events.push("end"); busyAtEnd = v.busy; } }));
    await flush(60);
    expect(events).toEqual(["start", "end"]);
    expect(busyAtEnd).toBe(false);
  });

  it("falls back (and still ends cleanly) when the voice server fails", async () => {
    fetchImpl = () => fail(502);
    const v = q();
    const ended = vi.fn();
    v.speak("fail me", opts({ onEnd: ended }));
    await flush(40);
    expect(FakeAudio.played).toEqual([]);
    expect(ended).toHaveBeenCalledTimes(1);   // no browser voice in this test env -> silent, but never stuck
    expect(v.busy).toBe(false);
  });

  it("stops calling the server for a while after a 429", async () => {
    const calls: string[] = [];
    fetchImpl = ({ text }) => { calls.push(text); return fail(429, "30"); };
    const v = q();
    v.speak("a", opts());
    await flush(30);
    v.speak("b", opts());
    await flush(30);
    expect(calls).toEqual(["a"]);
  });

  it("does not use the server when it is not enabled", async () => {
    fetchImpl = () => { throw new Error("should not fetch"); };
    expect(q(false).speak("x", opts())).toBe(false);   // browser voice unavailable in tests -> false, no fetch
  });

  it("cancel drops queued audio and resets busy", async () => {
    fetchImpl = ({ text }) => ok(text, 30);
    const v = q();
    v.speak("a", opts());
    v.speak("b", opts());
    expect(v.busy).toBe(true);
    v.cancel();
    expect(v.busy).toBe(false);
    await flush(100);
    expect(FakeAudio.played).toEqual([]);
  });

  it("speaks nothing when disabled", () => {
    const v = q();
    v.setEnabled(false);
    expect(v.speak("x", opts())).toBe(false);
  });
});

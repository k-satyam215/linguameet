// Natural translated voice. Sentences are synthesized by the server (/api/tts) and played in order;
// if the server voice is unavailable, slow, or rate-limited, that sentence falls back to the
// browser's own speech voice, so the meeting never goes silent. Captions are unaffected.
import { fetchTts, TtsError } from "./api";
import { SpeakOpts, SpeechQueue } from "./tts";

type Cfg = {
  getToken: () => string;
  serverTts: () => boolean;
  fetchTimeoutMs?: number;
};

export class VoiceQueue {
  private fallback = new SpeechQueue();
  private enabled = true;
  private chain: Promise<void> = Promise.resolve();
  private pending = 0;
  private gen = 0;
  private current: HTMLAudioElement | null = null;
  private pauseFetchUntil = 0;

  constructor(private cfg: Cfg) {}

  setEnabled(v: boolean) {
    this.enabled = v;
    if (!v) this.cancel();
  }

  get busy(): boolean {
    return this.pending > 0 || this.fallback.busy;
  }

  speak(text: string, o: SpeakOpts): boolean {
    if (!this.enabled || !text.trim()) return false;
    if (!this.cfg.serverTts() || typeof Audio === "undefined") return this.fallback.speak(text, o);

    const gen = this.gen;
    this.pending += 1;
    // Start synthesizing immediately (in parallel) but play strictly in order.
    const audio: Promise<Blob | null> =
      Date.now() < this.pauseFetchUntil ? Promise.resolve(null) : this.fetchAudio(text, o.speakerId);

    this.chain = this.chain.then(async () => {
      const blob = await audio;
      if (gen !== this.gen) return; // cancelled while waiting
      const finish = () => {
        if (gen !== this.gen) return;
        this.pending = Math.max(0, this.pending - 1);
        o.onEnd?.();
      };
      if (!blob) {
        const spoke = this.fallback.speak(text, { ...o, onEnd: finish });
        if (!spoke) finish();
        else await this.waitFallback();
        return;
      }
      await this.play(blob, o, finish);
    });
    return true;
  }

  cancel() {
    this.gen += 1;
    this.pending = 0;
    this.chain = Promise.resolve();
    if (this.current) {
      this.current.pause();
      this.current = null;
    }
    this.fallback.cancel();
  }

  private async fetchAudio(text: string, speakerId: string): Promise<Blob | null> {
    try {
      return await fetchTts(this.cfg.getToken(), text, speakerId, this.cfg.fetchTimeoutMs ?? 8000);
    } catch (e) {
      const status = e instanceof TtsError ? e.status : 0;
      const wait = status === 429 ? Math.max(5, (e as TtsError).retryAfter || 20) : 5;
      this.pauseFetchUntil = Date.now() + wait * 1000; // do not hammer a failing/limited voice server
      return null;
    }
  }

  private waitFallback(): Promise<void> {
    return new Promise((resolve) => {
      const t = setInterval(() => {
        if (!this.fallback.busy) {
          clearInterval(t);
          resolve();
        }
      }, 80);
    });
  }

  private play(blob: Blob, o: SpeakOpts, finish: () => void): Promise<void> {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(blob);
      const a = new Audio(url);
      this.current = a;
      let ended = false;
      const end = () => {
        if (ended) return;
        ended = true;
        URL.revokeObjectURL(url);
        if (this.current === a) this.current = null;
        finish();
        resolve();
      };
      a.onended = end;
      a.onerror = end;
      a.play().then(() => o.onStart?.()).catch(end);
    });
  }
}

// Browser speechSynthesis (free, no server cost). Each speaker gets a consistent
// preset voice + pitch so Rahul and Priya do not sound alike. This is Level A
// (preset voices), not voice cloning. Voice availability depends on OS/browser.

export type SpeakOpts = {
  speakerId: string;
  lang: string; // BCP-47, e.g. "hi-IN"
  onStart?: () => void;
  onEnd?: () => void;
};

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function voicesFor(lang: string): SpeechSynthesisVoice[] {
  if (typeof speechSynthesis === "undefined") return [];
  const prefix = lang.split("-")[0].toLowerCase();
  const all = speechSynthesis.getVoices();
  const exact = all.filter((v) => v.lang.toLowerCase() === lang.toLowerCase());
  const loose = all.filter((v) => v.lang.toLowerCase().startsWith(prefix));
  return exact.length ? exact : loose;
}

export function hasVoice(lang: string): boolean {
  return voicesFor(lang).length > 0;
}

export function pickVoice(speakerId: string, lang: string): { voice?: SpeechSynthesisVoice; pitch: number } {
  const list = voicesFor(lang).sort((a, b) => a.name.localeCompare(b.name));
  const h = hash(speakerId);
  const pitches = [0.85, 1.0, 1.15, 0.95, 1.1];
  return { voice: list.length ? list[h % list.length] : undefined, pitch: pitches[(h >> 3) % pitches.length] };
}

export class SpeechQueue {
  private pending = 0;
  private enabled = true;

  setEnabled(v: boolean) {
    this.enabled = v;
    if (!v) this.cancel();
  }

  speak(text: string, o: SpeakOpts): boolean {
    if (!this.enabled || typeof speechSynthesis === "undefined" || !text.trim()) return false;
    if (!hasVoice(o.lang)) return false;
    const u = new SpeechSynthesisUtterance(text);
    const { voice, pitch } = pickVoice(o.speakerId, o.lang);
    u.lang = o.lang;
    if (voice) u.voice = voice;
    u.pitch = pitch;
    u.rate = 1.05;
    u.onstart = () => {
      this.pending += 0;
      o.onStart?.();
    };
    const done = () => {
      this.pending = Math.max(0, this.pending - 1);
      o.onEnd?.();
    };
    u.onend = done;
    u.onerror = done;
    this.pending += 1;
    speechSynthesis.speak(u);
    return true;
  }

  get busy(): boolean {
    return this.pending > 0;
  }

  cancel() {
    this.pending = 0;
    if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
  }
}

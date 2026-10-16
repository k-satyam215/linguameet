"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { FALLBACK_LANGS, Lang, fetchLanguages, randomRoom, validRoom } from "@/lib/api";

function Lobby() {
  const router = useRouter();
  const params = useSearchParams();
  const [langs, setLangs] = useState<Lang[]>(FALLBACK_LANGS);
  const [name, setName] = useState("");
  const [room, setRoom] = useState(params.get("room") ?? "");
  const [speak, setSpeak] = useState("hi-en");
  const [listen, setListen] = useState("en");
  const [error, setError] = useState("");

  useEffect(() => {
    fetchLanguages().then(setLangs);
    try {
      const saved = JSON.parse(localStorage.getItem("lm.profile") || "{}");
      if (saved.name) setName(saved.name);
      if (saved.speak) setSpeak(saved.speak);
      if (saved.listen) setListen(saved.listen);
    } catch {}
  }, []);

  const go = (code: string) => {
    setError("");
    if (!name.trim()) return setError("Enter your name.");
    if (!validRoom(code)) return setError("Room code: 3-40 letters, digits, - or _.");
    try {
      localStorage.setItem("lm.profile", JSON.stringify({ name: name.trim(), speak, listen }));
      sessionStorage.setItem("lm.join", JSON.stringify({ room: code, name: name.trim(), speak, listen }));
    } catch {}
    router.push(`/room/${encodeURIComponent(code)}`);
  };

  return (
    <main className="lobby">
      <div className="lobby-card">
        <div className="brand"><span className="brand-dot" />LinguaMeet</div>
        <p className="tagline">Video meetings where everyone speaks their own language and reads or hears it in theirs.</p>

        <label className="field">
          <span>Your name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} placeholder="e.g. Satyam" />
        </label>

        <div className="row">
          <label className="field">
            <span>I speak</span>
            <select className="select" value={speak} onChange={(e) => setSpeak(e.target.value)}>
              <option value="auto">Auto-detect</option>
              {langs.filter((l) => l.asr).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
          </label>
          <label className="field">
            <span>I want to hear</span>
            <select className="select" value={listen} onChange={(e) => setListen(e.target.value)}>
              {langs.filter((l) => l.translate).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
          </label>
        </div>

        {error && <div className="error">{error}</div>}

        <button className="btn" onClick={() => go(randomRoom())}>Start a new meeting</button>
        <div className="divider">or join with a code</div>
        <label className="field">
          <input className="input" value={room} onChange={(e) => setRoom(e.target.value.trim())} placeholder="abc-defg-hij" />
        </label>
        <button className="btn ghost" onClick={() => go(room)} disabled={!room}>Join meeting</button>

        <p className="hint">
          Use headphones for the best experience. Translated voice uses voices installed on your device;
          if none exists for your language you still get live translated captions.
        </p>
      </div>
    </main>
  );
}

export default function Page() {
  return (
    <Suspense fallback={null}>
      <Lobby />
    </Suspense>
  );
}

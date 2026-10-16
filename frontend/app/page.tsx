"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import Brand from "@/components/Brand";
import Icon from "@/components/Icon";
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
    router.push("/room/" + encodeURIComponent(code));
  };

  return (
    <main className="lobby lobby-page">
      <div className="lobby-shell">
        <header className="site-header">
          <Brand />
          <div className="site-status"><span className="status-dot" /> LIVE LANGUAGE TOOLS</div>
        </header>

        <section className="hero-grid">
          <div className="hero-copy">
            <div className="eyebrow"><span /> MADE FOR HUMAN CONVERSATION</div>
            <h1>Your language.<br /><span>Everyone’s in.</span></h1>
            <p className="hero-description">
              Speak Hindi, Hinglish, or English. Follow every thought with live captions and optional translated speech.
            </p>

            <div className="translation-preview">
              <div className="preview-topline">
                <span><span className="live-dot" /> EXAMPLE TRANSLATION</span>
                <span className="language-pair">HINGLISH <Icon name="arrow" /> ENGLISH</span>
              </div>
              <div className="preview-message">
                <div className="preview-avatar avatar-hindi">हि</div>
                <div className="preview-message-copy">
                  <span className="preview-label">ORIGINAL · HINGLISH</span>
                  <p>Kal meeting ka agenda bhej dena,<br />deadline Friday hai.</p>
                </div>
              </div>
              <div className="preview-divider"><span /><span>TRANSLATED FOR YOUR GUEST</span><span /></div>
              <div className="preview-message preview-message-translated">
                <div className="preview-avatar avatar-english">EN</div>
                <div className="preview-message-copy">
                  <span className="preview-label">ENGLISH · CAPTIONS + VOICE</span>
                  <p>Send the meeting agenda tomorrow.<br /><strong>The deadline is Friday.</strong></p>
                </div>
              </div>
              <div className="preview-foot">
                <span><Icon name="captions" /> Live translated captions</span>
                <span><Icon name="volume" /> Optional voice</span>
              </div>
            </div>

            <div className="hero-assurance">
              <span className="assurance-icon"><Icon name="globe" /></span>
              <span>One call. Different languages. A conversation that keeps flowing.</span>
            </div>
          </div>

          <section className="lobby-card" aria-labelledby="start-heading">
            <div className="card-eyebrow"><span>QUICK START</span><span className="free-badge">No install</span></div>
            <h2 id="start-heading">Start your meeting</h2>
            <p className="card-intro">Set your languages, then invite someone to join.</p>

            <label className="field">
              <span>Your name</span>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} placeholder="e.g. Satyam" autoComplete="name" />
            </label>

            <div className="language-heading"><span>YOUR LANGUAGES</span><span>Change anytime</span></div>
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

            {error && <div className="error" role="alert">{error}</div>}

            <button className="btn start-button" onClick={() => go(randomRoom())}>
              <span>Start a new meeting</span><span className="button-arrow"><Icon name="arrow" /></span>
            </button>

            <div className="divider"><span>OR JOIN AN EXISTING ROOM</span></div>
            <label className="field room-field">
              <span>Meeting link or room code</span>
              <input className="input" value={room} onChange={(e) => setRoom(e.target.value.trim())} placeholder="abc-defg-hij" autoComplete="off" />
            </label>
            <button className="btn ghost join-button" onClick={() => go(room)} disabled={!room}>
              <Icon name="link" /> Join meeting
            </button>

            <div className="card-note"><Icon name="spark" /><span>Preview your camera and microphone before you enter.</span></div>
          </section>
        </section>

        <footer className="site-footer">
          <span>LINGUAMEET <i /> EVERY VOICE, UNDERSTOOD.</span>
          <span>VIDEO CALLS · LIVE CAPTIONS · TRANSLATED VOICE</span>
        </footer>
      </div>
    </main>
  );
}

export default function Page() {
  return <Suspense fallback={<main className="lobby lobby-page" />}><Lobby /></Suspense>;
}

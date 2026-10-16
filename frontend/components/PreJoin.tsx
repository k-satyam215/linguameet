"use client";

import { useEffect, useRef, useState } from "react";
import type { Lang } from "@/lib/api";

export type JoinSelection = {
  name: string;
  speak: string;
  listen: string;
  micOn: boolean;
  camOn: boolean;
  micId: string;
  camId: string;
};

export default function PreJoin({
  code, langs, initial, busy, error, onJoin, onBack,
}: {
  code: string;
  langs: Lang[];
  initial: { name: string; speak: string; listen: string };
  busy: boolean;
  error: string;
  onJoin: (s: JoinSelection) => void;
  onBack: () => void;
}) {
  const [name, setName] = useState(initial.name);
  const [speak, setSpeak] = useState(initial.speak);
  const [listen, setListen] = useState(initial.listen);
  const [micOn, setMicOn] = useState(true);
  const [camOn, setCamOn] = useState(true);
  const [micId, setMicId] = useState("");
  const [camId, setCamId] = useState("");
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [cams, setCams] = useState<MediaDeviceInfo[]>([]);
  const [perm, setPerm] = useState("");
  const [level, setLevel] = useState(0);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stopStream = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };

  useEffect(() => {
    let cancelled = false;
    let raf = 0;
    let ctx: AudioContext | undefined;

    (async () => {
      stopStream();
      setLevel(0);
      try {
        if (micOn || camOn) {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: micOn ? (micId ? { deviceId: { ideal: micId } } : true) : false,
            video: camOn ? (camId ? { deviceId: { ideal: camId } } : true) : false,
          });
          if (cancelled) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          streamRef.current = stream;
          setPerm("");
          if (videoRef.current) videoRef.current.srcObject = stream;

          if (micOn && stream.getAudioTracks().length) {
            ctx = new AudioContext();
            const an = ctx.createAnalyser();
            an.fftSize = 512;
            ctx.createMediaStreamSource(stream).connect(an);
            const buf = new Uint8Array(an.fftSize);
            let last = 0;
            const tick = () => {
              an.getByteTimeDomainData(buf);
              let sum = 0;
              for (let i = 0; i < buf.length; i++) {
                const v = (buf[i] - 128) / 128;
                sum += v * v;
              }
              const lvl = Math.min(100, Math.round(Math.sqrt(sum / buf.length) * 300));
              if (Math.abs(lvl - last) >= 3) {
                last = lvl;
                setLevel(lvl);
              }
              raf = requestAnimationFrame(tick);
            };
            tick();
          }
        }
        const list = await navigator.mediaDevices.enumerateDevices();
        if (!cancelled) {
          setMics(list.filter((d) => d.kind === "audioinput"));
          setCams(list.filter((d) => d.kind === "videoinput"));
        }
      } catch (e: any) {
        if (!cancelled) setPerm(`Camera/microphone unavailable: ${e?.message || e?.name || "permission denied"}. You can still join.`);
      }
    })();

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      void ctx?.close();
      stopStream();
    };
  }, [micOn, camOn, micId, camId]);

  const join = () => {
    stopStream(); // release devices so LiveKit can take them
    onJoin({ name: name.trim(), speak, listen, micOn, camOn, micId, camId });
  };

  return (
    <main className="lobby">
      <div className="prejoin">
        <div className="prejoin-preview">
          <div className="tile preview-tile">
            {camOn ? (
              <video ref={videoRef} autoPlay playsInline muted style={{ transform: "scaleX(-1)" }} />
            ) : (
              <div className="avatar"><span>{(name || "?").slice(0, 1).toUpperCase()}</span></div>
            )}
            <div className="preview-controls">
              <button className={`ctl ${micOn ? "" : "off"}`} onClick={() => setMicOn((v) => !v)} aria-label="Toggle microphone">🎙</button>
              <button className={`ctl ${camOn ? "" : "off"}`} onClick={() => setCamOn((v) => !v)} aria-label="Toggle camera">📷</button>
            </div>
          </div>
          {micOn && (
            <div className="meter" aria-label="Microphone level"><div style={{ width: `${level}%` }} /></div>
          )}
          {perm && <div className="banner">{perm}</div>}
        </div>

        <div className="lobby-card prejoin-form">
          <div className="brand"><span className="brand-dot" />Ready to join?</div>
          <p className="tagline">Meeting <strong>{code}</strong></p>

          <label className="field">
            <span>Your name</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} />
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
          <label className="field">
            <span>Microphone</span>
            <select className="select" value={micId} onChange={(e) => setMicId(e.target.value)}>
              <option value="">Default</option>
              {mics.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `Microphone ${i + 1}`}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Camera</span>
            <select className="select" value={camId} onChange={(e) => setCamId(e.target.value)}>
              <option value="">Default</option>
              {cams.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
            </select>
          </label>

          {error && <div className="error">{error}</div>}
          <button className="btn" onClick={join} disabled={busy || !name.trim()}>{busy ? "Joining…" : "Join now"}</button>
          <button className="btn ghost" style={{ marginTop: 8 }} onClick={onBack}>Back</button>
        </div>
      </div>
    </main>
  );
}

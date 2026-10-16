"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Lang, wsUrl } from "./api";
import { MicStreamer } from "./micStreamer";
import { completedSentences, remainder } from "./sentences";
import { SpeechQueue, hasVoice } from "./tts";

export type Timings = { asr_ms?: number; first_token_ms?: number; translate_ms?: number; e2e_ms?: number; since_speech_end_ms?: number };

export type CaptionItem = {
  id: string;
  speaker: string;
  speakerName: string;
  original?: { lang: string; text: string; timings?: Timings };
  translation?: { lang: string; text: string; final: boolean; timings?: Timings };
  at: number;
};

export type Participant = { identity: string; name: string; speak: string; listen: string };
export type Conn = "connecting" | "open" | "reconnecting" | "closed";

type Opts = {
  token: string;
  identity: string;
  speak: string;
  listen: string;
  langs: Lang[];
  voiceOn: boolean;
  micOn: boolean;
  pauseMicWhileSpeaking: boolean;
  micDeviceId?: string;
};

export function useTranslation(o: Opts) {
  const [conn, setConn] = useState<Conn>("connecting");
  const [captions, setCaptions] = useState<CaptionItem[]>([]);
  const [roster, setRoster] = useState<Participant[]>([]);
  const [glossary, setGlossary] = useState<string[]>([]);
  const [notice, setNotice] = useState<string>("");
  const [lastE2E, setLastE2E] = useState<Timings | null>(null);
  const [rtt, setRtt] = useState<number | null>(null);
  const [micError, setMicError] = useState<string>("");
  const [host, setHost] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [removed, setRemoved] = useState(false);

  const ws = useRef<WebSocket | null>(null);
  const mic = useRef<MicStreamer>(new MicStreamer());
  const speech = useRef<SpeechQueue>(new SpeechQueue());
  const spoken = useRef<Map<string, number>>(new Map());
  const optsRef = useRef(o);
  optsRef.current = o;
  const closed = useRef(false);
  const attempt = useRef(0);
  const unpauseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const send = useCallback((obj: unknown) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(obj));
  }, []);

  const bcp47 = useCallback(
    (code: string) => optsRef.current.langs.find((l) => l.code === code)?.bcp47 ?? "en-US",
    []
  );

  const speak = useCallback(
    (text: string, speaker: string) => {
      const cur = optsRef.current;
      if (!cur.voiceOn) return;
      const lang = bcp47(cur.listen);
      speech.current.speak(text, {
        speakerId: speaker,
        lang,
        onStart: () => {
          if (cur.pauseMicWhileSpeaking && !mic.current.paused) {
            mic.current.paused = true;
            send({ type: "flush" });
          }
          if (unpauseTimer.current) clearTimeout(unpauseTimer.current);
        },
        onEnd: () => {
          if (speech.current.busy) return;
          if (unpauseTimer.current) clearTimeout(unpauseTimer.current);
          unpauseTimer.current = setTimeout(() => {
            if (!speech.current.busy) mic.current.paused = !optsRef.current.micOn;
          }, 350);
        },
      });
    },
    [bcp47, send]
  );

  const onEvent = useCallback(
    (ev: any) => {
      switch (ev.type) {
        case "roster":
          setRoster(ev.participants ?? []);
          setGlossary(ev.glossary ?? []);
          setHost(ev.host ?? null);
          setLocked(!!ev.locked);
          break;
        case "status":
          setNotice(ev.message ?? ev.code);
          setTimeout(() => setNotice(""), 6000);
          break;
        case "pong":
          if (typeof ev.t === "number") setRtt(Math.round(performance.now() - ev.t));
          break;
        case "caption": {
          setCaptions((prev) => {
            const i = prev.findIndex((c) => c.id === ev.id);
            const base: CaptionItem =
              i >= 0 ? { ...prev[i] } : { id: ev.id, speaker: ev.speaker, speakerName: ev.speakerName, at: Date.now() };
            if (ev.kind === "original") base.original = { lang: ev.lang, text: ev.text, timings: ev.timings };
            else base.translation = { lang: ev.lang, text: ev.text, final: ev.final, timings: ev.timings };
            const next = i >= 0 ? prev.map((c, j) => (j === i ? base : c)) : [...prev, base];
            return next.slice(-60);
          });
          if (ev.kind === "translation") {
            const from = spoken.current.get(ev.id) ?? 0;
            const { sentences, next } = completedSentences(ev.text + (ev.final ? " " : ""), from);
            sentences.forEach((s) => speak(s, ev.speaker));
            let idx = next;
            if (ev.final) {
              const rest = remainder(ev.text, idx);
              if (rest) speak(rest, ev.speaker);
              idx = ev.text.length;
              if (ev.timings) setLastE2E(ev.timings);
            }
            spoken.current.set(ev.id, idx);
          }
          break;
        }
      }
    },
    [speak]
  );

  // ---- websocket with exponential backoff + jitter ---------------------
  useEffect(() => {
    closed.current = false;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      setConn(attempt.current === 0 ? "connecting" : "reconnecting");
      const sock = new WebSocket(wsUrl(optsRef.current.token));
      sock.binaryType = "arraybuffer";
      ws.current = sock;
      sock.onopen = () => {
        attempt.current = 0;
        setConn("open");
        sock.send(JSON.stringify({ type: "prefs", speak: optsRef.current.speak, listen: optsRef.current.listen }));
        pingTimer = setInterval(() => sock.readyState === WebSocket.OPEN && sock.send(JSON.stringify({ type: "ping", t: performance.now() })), 5000);
      };
      sock.onmessage = (m) => {
        if (typeof m.data === "string") {
          try {
            onEvent(JSON.parse(m.data));
          } catch {}
        }
      };
      sock.onclose = (e) => {
        if (pingTimer) clearInterval(pingTimer);
        if (closed.current) return;
        if (e.code === 4410) {
          setConn("closed");
          setRemoved(true);
          return;
        }
        if (e.code === 4401 || e.code === 4403) {
          setConn("closed");
          setNotice(e.code === 4403 ? "Room is full." : "Session expired. Please rejoin.");
          return;
        }
        attempt.current += 1;
        const delay = Math.min(8000, 400 * 2 ** attempt.current) * (0.6 + Math.random() * 0.8);
        setConn("reconnecting");
        retry = setTimeout(connect, delay);
      };
      sock.onerror = () => sock.close();
    };
    connect();

    return () => {
      closed.current = true;
      if (pingTimer) clearInterval(pingTimer);
      if (retry) clearTimeout(retry);
      ws.current?.close();
      speech.current.cancel();
    };
  }, [o.token, onEvent]);

  // ---- mic -------------------------------------------------------------
  useEffect(() => {
    const m = mic.current;
    let cancelled = false;
    m.start((pcm) => {
      if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(pcm);
    }, optsRef.current.micDeviceId)
      .then(() => !cancelled && setMicError(""))
      .catch((e) => !cancelled && setMicError(e?.message || "Microphone unavailable"));
    return () => {
      cancelled = true;
      m.stop();
    };
  }, []);

  useEffect(() => {
    mic.current.paused = !o.micOn;
    if (!o.micOn) send({ type: "flush" });
  }, [o.micOn, send]);

  // ---- prefs / voice toggles ------------------------------------------
  useEffect(() => {
    if (conn === "open") send({ type: "prefs", speak: o.speak, listen: o.listen });
  }, [o.speak, o.listen, conn, send]);

  useEffect(() => {
    speech.current.setEnabled(o.voiceOn);
  }, [o.voiceOn]);

  const updateGlossary = useCallback((terms: string[]) => send({ type: "glossary", terms }), [send]);
  const [voiceAvailable, setVoiceAvailable] = useState<boolean | null>(null);

  // Browser speech engines commonly expose voices asynchronously. Re-check when
  // the platform finishes loading them so the UI does not keep a false warning.
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.speechSynthesis === "undefined") {
      setVoiceAvailable(false);
      return;
    }
    const synth = window.speechSynthesis;
    const desiredLang = bcp47(o.listen);
    const refresh = () => setVoiceAvailable(hasVoice(desiredLang));
    refresh();
    synth.addEventListener("voiceschanged", refresh);
    const retry = window.setTimeout(refresh, 1000);
    return () => {
      synth.removeEventListener("voiceschanged", refresh);
      window.clearTimeout(retry);
    };
  }, [o.listen, o.langs, bcp47]);

  return { conn, captions, roster, glossary, notice, lastE2E, rtt, micError, updateGlossary, voiceAvailable, host, locked, removed };
}

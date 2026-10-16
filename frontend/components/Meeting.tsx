"use client";

import {
  ConnectionState, DisconnectReason, Participant as LKParticipant, RemoteParticipant, Room, RoomEvent, Track,
} from "livekit-client";
import { FormEvent, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { JoinInfo, Lang, hostAction } from "@/lib/api";
import { ChatMsg, EMOJIS, MAX_CHAT, encode, parseChat, parseReaction, uid } from "@/lib/realtime";
import { useTranslation } from "@/lib/useTranslation";
import { VideoGrid } from "./VideoGrid";

type Tab = "captions" | "chat" | "people" | "settings";
type Float = { id: string; emoji: string; x: number };

export default function Meeting({
  code, name, join, langs, initialSpeak, initialListen, initialMicOn, initialCamOn, micId, camId, onLeave,
}: {
  code: string;
  name: string;
  join: JoinInfo;
  langs: Lang[];
  initialSpeak: string;
  initialListen: string;
  initialMicOn: boolean;
  initialCamOn: boolean;
  micId: string;
  camId: string;
  onLeave: () => void;
}) {
  const [speak, setSpeak] = useState(initialSpeak);
  const [listen, setListen] = useState(initialListen);
  const [voiceOn, setVoiceOn] = useState(true);
  const [pauseMic, setPauseMic] = useState(true);
  const [duck, setDuck] = useState(true);
  const [captionsOn, setCaptionsOn] = useState(true);
  const [micOn, setMicOn] = useState(initialMicOn);
  const [camOn, setCamOn] = useState(initialCamOn);
  const [sharing, setSharing] = useState(false);
  const [tab, setTab] = useState<Tab>("captions");
  const [lkState, setLkState] = useState<ConnectionState>(ConnectionState.Connecting);
  const [lkError, setLkError] = useState("");
  const [lkRemoved, setLkRemoved] = useState(false);
  const [active, setActive] = useState<string[]>([]);
  const [, bump] = useReducer((x: number) => x + 1, 0);
  const [glossaryText, setGlossaryText] = useState("");

  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [unread, setUnread] = useState(0);
  const [draft, setDraft] = useState("");
  const [hands, setHands] = useState<string[]>([]);
  const [handUp, setHandUp] = useState(false);
  const [floats, setFloats] = useState<Float[]>([]);
  const [reactOpen, setReactOpen] = useState(false);
  const [pinned, setPinned] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [toast, setToast] = useState("");

  const room = useMemo(() => new Room({ adaptiveStream: true, dynacast: true }), []);
  const capsEnd = useRef<HTMLDivElement>(null);
  const chatEnd = useRef<HTMLDivElement>(null);
  const tabRef = useRef<Tab>("captions");
  const handRef = useRef(false);
  tabRef.current = tab;
  handRef.current = handUp;

  const tr = useTranslation({
    token: join.ws_token, identity: join.identity, speak, listen, langs,
    voiceOn, micOn, pauseMicWhileSpeaking: pauseMic, micDeviceId: micId,
  });
  const isHost = tr.host === join.identity;

  const flash = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast((t) => (t === msg ? "" : t)), 5000);
  }, []);

  const publish = useCallback(
    async (topic: "chat" | "reaction", obj: unknown) => {
      try {
        await room.localParticipant.publishData(encode(obj) as Uint8Array<ArrayBuffer>, { reliable: true, topic });
        return true;
      } catch {
        return false;
      }
    },
    [room]
  );

  const addFloat = useCallback((emoji: string) => {
    const f: Float = { id: uid(), emoji, x: 10 + Math.random() * 80 };
    setFloats((cur) => [...cur, f].slice(-12));
    setTimeout(() => setFloats((cur) => cur.filter((x) => x.id !== f.id)), 3200);
  }, []);

  // ---- LiveKit lifecycle ------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const refresh = () => bump();
    room
      .on(RoomEvent.ParticipantConnected, () => {
        bump();
        // Late joiners cannot see an already-raised hand unless we say it again.
        if (handRef.current) void publish("reaction", { hand: true });
      })
      .on(RoomEvent.ParticipantDisconnected, (p: RemoteParticipant) => {
        setHands((h) => h.filter((id) => id !== p.identity));
        setPinned((k) => (k && k.startsWith(`${p.identity}-`) ? null : k));
        bump();
      })
      .on(RoomEvent.TrackSubscribed, refresh)
      .on(RoomEvent.TrackUnsubscribed, refresh)
      .on(RoomEvent.TrackMuted, (pub, p) => {
        // The host may mute us from the server side: keep our UI honest.
        if (p.isLocal && pub.source === Track.Source.Microphone) {
          setMicOn(false);
          flash("You were muted by the host.");
        }
        bump();
      })
      .on(RoomEvent.TrackUnmuted, refresh)
      .on(RoomEvent.LocalTrackPublished, refresh)
      .on(RoomEvent.LocalTrackUnpublished, refresh)
      .on(RoomEvent.ActiveSpeakersChanged, (s: LKParticipant[]) => setActive(s.map((p) => p.identity)))
      .on(RoomEvent.ConnectionStateChanged, (s: ConnectionState) => setLkState(s))
      .on(RoomEvent.Disconnected, (reason?: DisconnectReason) => {
        if (reason === DisconnectReason.PARTICIPANT_REMOVED) setLkRemoved(true);
      })
      .on(RoomEvent.DataReceived, (payload: Uint8Array, p?: RemoteParticipant, _kind?: unknown, topic?: string) => {
        if (!p) return;
        const raw = new TextDecoder().decode(payload);
        if (topic === "chat") {
          const text = parseChat(raw);
          if (!text) return;
          setChat((c) => [...c, { id: uid(), from: p.identity, name: p.name || p.identity, text, at: Date.now() }].slice(-200));
          if (tabRef.current !== "chat") setUnread((u) => u + 1);
        } else if (topic === "reaction") {
          const r = parseReaction(raw);
          if (!r) return;
          if (r.kind === "hand") setHands((h) => (r.on ? (h.includes(p.identity) ? h : [...h, p.identity]) : h.filter((id) => id !== p.identity)));
          else addFloat(r.emoji);
        }
      });

    (async () => {
      try {
        await room.connect(join.livekit_url, join.livekit_token);
        if (cancelled) return;
        if (initialMicOn) {
          await room.localParticipant
            .setMicrophoneEnabled(true, micId ? { deviceId: micId } : undefined)
            .catch(() => setMicOn(false));
        }
        if (initialCamOn) {
          await room.localParticipant
            .setCameraEnabled(true, camId ? { deviceId: camId } : undefined)
            .catch(() => setCamOn(false));
        }
        bump();
      } catch (e: any) {
        setLkError(e?.message || "Could not connect to the video server. Is LiveKit running?");
      }
    })();

    return () => {
      cancelled = true;
      void room.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [room, join.livekit_url, join.livekit_token]);

  useEffect(() => {
    if (tab === "captions") capsEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    if (tab === "chat") chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [tr.captions.length, chat.length, tab]);

  useEffect(() => {
    if (tab === "chat") setUnread(0);
  }, [tab, chat.length]);

  // ---- controls ---------------------------------------------------------
  const toggleMic = async () => {
    const next = !micOn;
    setMicOn(next);
    await room.localParticipant.setMicrophoneEnabled(next, next && micId ? { deviceId: micId } : undefined).catch(() => {});
  };
  const toggleCam = async () => {
    const next = !camOn;
    setCamOn(next);
    await room.localParticipant.setCameraEnabled(next, next && camId ? { deviceId: camId } : undefined).catch(() => setCamOn(false));
  };
  const toggleShare = async () => {
    try {
      const next = !sharing;
      await room.localParticipant.setScreenShareEnabled(next);
      setSharing(next);
    } catch {
      setSharing(false);
    }
  };
  const toggleHand = async () => {
    const next = !handUp;
    setHandUp(next);
    setHands((h) => (next ? [...h.filter((i) => i !== join.identity), join.identity] : h.filter((i) => i !== join.identity)));
    if (!(await publish("reaction", { hand: next }))) flash("Could not send hand signal.");
  };
  const react = async (emoji: string) => {
    setReactOpen(false);
    addFloat(emoji);
    await publish("reaction", { emoji });
  };
  const sendChat = async (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim().slice(0, MAX_CHAT);
    if (!text) return;
    setDraft("");
    setChat((c) => [...c, { id: uid(), from: join.identity, name, text, at: Date.now() }].slice(-200));
    if (!(await publish("chat", { text }))) flash("Message could not be sent.");
  };
  const copyInvite = async () => {
    const link = `${window.location.origin}/?room=${encodeURIComponent(code)}`;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy this invite link:", link);
    }
  };
  const leave = () => {
    void room.disconnect();
    onLeave();
  };
  const saveGlossary = () =>
    tr.updateGlossary(glossaryText.split(/[\n,]/).map((t) => t.trim()).filter(Boolean));

  const host = async (action: "mute" | "remove" | "lock", body: { target?: string; locked?: boolean }) => {
    try {
      await hostAction(join.ws_token, action, body);
    } catch (e: any) {
      flash(e?.message || "Host action failed");
    }
  };

  const connPill = tr.conn === "open" ? "ok" : tr.conn === "closed" ? "bad" : "warn";
  const lkPill = lkState === ConnectionState.Connected ? "ok" : lkState === ConnectionState.Disconnected ? "bad" : "warn";
  const langName = (c: string) => langs.find((l) => l.code === c)?.name ?? c;

  const latest = [...tr.captions].reverse().find((c) => c.translation || c.original);
  const remote = Array.from(room.remoteParticipants.values());
  const showVoiceWarn = voiceOn && tr.voiceAvailable === false;
  const removed = lkRemoved || tr.removed;

  if (removed) {
    return (
      <main className="lobby">
        <div className="lobby-card">
          <div className="error">You were removed from this meeting by the host.</div>
          <button className="btn ghost" onClick={leave}>Back to home</button>
        </div>
      </main>
    );
  }

  const tabLabel: Record<Tab, string> = {
    captions: "Transcript",
    chat: unread ? `Chat (${unread})` : "Chat",
    people: `People (${tr.roster.length})`,
    settings: "Translation",
  };

  return (
    <div className="meeting">
      <div className="topbar">
        <div className="left">
          <strong>{code}</strong>
          <button className="pill action" onClick={copyInvite}>{copied ? "✓ Link copied" : "🔗 Copy invite link"}</button>
          <span className={`pill ${lkPill}`}><span className="dot" />Video {lkState}</span>
          <span className={`pill ${connPill}`}><span className="dot" />Translation {tr.conn}</span>
          {tr.locked && <span className="pill warn"><span className="dot" />Locked</span>}
        </div>
        <div className="pill">
          You speak {langName(speak)} · hear {langName(listen)}
          {tr.rtt !== null && <> · RTT {tr.rtt} ms</>}
        </div>
      </div>

      <div className="stage">
        <div className="grid-wrap">
          {lkError && <div className="error">{lkError}</div>}
          {tr.micError && <div className="banner">Translation mic: {tr.micError}. Captions for your speech won&apos;t work.</div>}
          {tr.notice && <div className="banner">{tr.notice}</div>}
          {toast && <div className="banner">{toast}</div>}
          {showVoiceWarn && (
            <div className="banner">
              This browser cannot access a speech voice for {langName(listen)}. Captions still work; spoken translations need a matching system voice.
            </div>
          )}
          <VideoGrid
            participants={remote}
            local={room.localParticipant}
            localName={name}
            roster={tr.roster}
            langs={langs}
            activeSpeakers={active}
            duck={duck && voiceOn}
            hands={hands}
            pinned={pinned}
            onPin={setPinned}
          />
          {captionsOn && (
            <div className="live-caption" aria-live="polite">
              {latest ? (
                <>
                  <div className="who">{latest.speakerName}</div>
                  <div className="tr">{latest.translation?.text ?? latest.original?.text}</div>
                  {latest.translation && latest.original && <div className="orig">{latest.original.text}</div>}
                </>
              ) : (
                <div className="empty">Live captions will appear here when someone speaks.</div>
              )}
            </div>
          )}
          <div className="floats" aria-hidden>
            {floats.map((f) => (
              <span key={f.id} className="float" style={{ left: `${f.x}%` }}>{f.emoji}</span>
            ))}
          </div>
        </div>

        <aside className="side">
          <div className="tabs">
            {(["captions", "chat", "people", "settings"] as Tab[]).map((t) => (
              <button key={t} className={`tab ${tab === t ? "on" : ""}`} onClick={() => setTab(t)}>{tabLabel[t]}</button>
            ))}
          </div>
          <div className="side-body">
            {tab === "captions" && (
              <>
                {tr.captions.length === 0 && <div className="hint">Nothing yet. Speak, or ask someone to.</div>}
                {tr.captions.map((c) => (
                  <div className="cap" key={c.id}>
                    <div className="meta">
                      <b>{c.speakerName}</b>
                      {c.original && <> · {langName(c.original.lang)}</>}
                      {c.translation?.timings?.e2e_ms !== undefined && <> · {(c.translation.timings.e2e_ms / 1000).toFixed(1)}s</>}
                    </div>
                    <div className={`t ${c.translation && !c.translation.final ? "partial" : ""}`}>
                      {c.translation?.text ?? c.original?.text}
                    </div>
                    {c.translation && c.original && <div className="o">{c.original.text}</div>}
                  </div>
                ))}
                <div ref={capsEnd} />
              </>
            )}

            {tab === "chat" && (
              <>
                {chat.length === 0 && <div className="hint">Messages are visible to everyone in the meeting and are not saved.</div>}
                {chat.map((m) => (
                  <div className={`bubble ${m.from === join.identity ? "mine" : ""}`} key={m.id}>
                    <div className="meta"><b>{m.from === join.identity ? "You" : m.name}</b> · {new Date(m.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
                    <div className="t">{m.text}</div>
                  </div>
                ))}
                <div ref={chatEnd} />
              </>
            )}

            {tab === "people" && (
              <>
                {isHost && (
                  <div className="host-bar">
                    <button className="btn ghost" onClick={() => host("mute", { target: "*" })}>🔇 Mute all</button>
                    <button className="btn ghost" onClick={() => host("lock", { locked: !tr.locked })}>
                      {tr.locked ? "🔓 Unlock room" : "🔒 Lock room"}
                    </button>
                  </div>
                )}
                {tr.roster.map((p) => (
                  <div className="person" key={p.identity}>
                    <div>
                      <div>
                        {p.name}{p.identity === join.identity ? " (You)" : ""}
                        {p.identity === tr.host && <span className="badge">Host</span>}
                        {hands.includes(p.identity) && " ✋"}
                      </div>
                      <small>{langName(p.speak)} → {langName(p.listen)}</small>
                    </div>
                    {isHost && p.identity !== join.identity && (
                      <div className="person-actions">
                        <button className="mini" onClick={() => host("mute", { target: p.identity })}>Mute</button>
                        <button className="mini danger" onClick={() => host("remove", { target: p.identity })}>Remove</button>
                      </div>
                    )}
                  </div>
                ))}
                {isHost && <div className="hint">Removed people can rejoin with the room code unless you lock the room.</div>}
              </>
            )}

            {tab === "settings" && (
              <>
                <div className="setting">
                  <label className="field">
                    <span>I speak</span>
                    <select className="select" value={speak} onChange={(e) => setSpeak(e.target.value)}>
                      <option value="auto">Auto-detect</option>
                      {langs.filter((l) => l.asr).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span>I want to hear / read</span>
                    <select className="select" value={listen} onChange={(e) => setListen(e.target.value)}>
                      {langs.filter((l) => l.translate).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
                    </select>
                  </label>
                </div>
                <div className="setting">
                  <label className="switch">
                    <span>Translated voice<small>Speaks translations using a voice installed on your device. Each speaker gets a consistent voice.</small></span>
                    <input type="checkbox" checked={voiceOn} onChange={(e) => setVoiceOn(e.target.checked)} />
                  </label>
                </div>
                <div className="setting">
                  <label className="switch">
                    <span>Lower original audio<small>Ducks the speaker&apos;s real voice while translated voice is on.</small></span>
                    <input type="checkbox" checked={duck} onChange={(e) => setDuck(e.target.checked)} />
                  </label>
                </div>
                <div className="setting">
                  <label className="switch">
                    <span>Pause my mic while voice plays<small>Prevents echo loops. Turn off only with headphones.</small></span>
                    <input type="checkbox" checked={pauseMic} onChange={(e) => setPauseMic(e.target.checked)} />
                  </label>
                </div>
                <div className="setting">
                  <label className="switch">
                    <span>Live caption bar</span>
                    <input type="checkbox" checked={captionsOn} onChange={(e) => setCaptionsOn(e.target.checked)} />
                  </label>
                </div>
                <div className="setting">
                  <div className="field">
                    <span>Meeting glossary (one term per line)</span>
                    <textarea
                      className="textarea"
                      value={glossaryText}
                      onChange={(e) => setGlossaryText(e.target.value)}
                      placeholder={"RepoMind\nLangGraph\nsprint review"}
                    />
                  </div>
                  <button className="btn ghost" onClick={saveGlossary}>Apply to room</button>
                  {tr.glossary.length > 0 && <div className="hint">Active: {tr.glossary.join(", ")}</div>}
                </div>
                <div className="setting">
                  <div className="stat"><span>Last translation (end-to-end)</span><b>{tr.lastE2E?.e2e_ms !== undefined ? `${(tr.lastE2E.e2e_ms / 1000).toFixed(2)} s` : "—"}</b></div>
                  <div className="stat"><span>Speech recognition</span><b>{tr.lastE2E?.asr_ms !== undefined ? `${tr.lastE2E.asr_ms} ms` : "—"}</b></div>
                  <div className="stat"><span>First translated words</span><b>{tr.lastE2E?.first_token_ms !== undefined ? `${tr.lastE2E.first_token_ms} ms` : "—"}</b></div>
                  <div className="hint">Measured from the moment you stop speaking, including the silence-detection wait.</div>
                </div>
              </>
            )}
          </div>

          {tab === "chat" && (
            <form className="chat-form" onSubmit={sendChat}>
              <input
                className="input"
                value={draft}
                maxLength={MAX_CHAT}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Message everyone"
                aria-label="Chat message"
              />
              <button className="mini send" type="submit" disabled={!draft.trim()}>Send</button>
            </form>
          )}
        </aside>
      </div>

      <div className="controls">
        <button className={`ctl ${micOn ? "" : "off"}`} onClick={toggleMic} aria-label="Toggle microphone">
          🎙<span className="txt">{micOn ? "Mute" : "Unmute"}</span>
        </button>
        <button className={`ctl ${camOn ? "" : "off"}`} onClick={toggleCam} aria-label="Toggle camera">
          📷<span className="txt">{camOn ? "Stop video" : "Start video"}</span>
        </button>
        <button className={`ctl ${sharing ? "on" : ""}`} onClick={toggleShare} aria-label="Share screen">
          🖥<span className="txt">{sharing ? "Stop sharing" : "Share"}</span>
        </button>
        <button className={`ctl ${handUp ? "on" : ""}`} onClick={toggleHand} aria-label="Raise hand">
          ✋<span className="txt">{handUp ? "Lower hand" : "Raise hand"}</span>
        </button>
        <div className="react-wrap">
          <button className={`ctl ${reactOpen ? "on" : ""}`} onClick={() => setReactOpen((v) => !v)} aria-label="Reactions">
            😊<span className="txt">React</span>
          </button>
          {reactOpen && (
            <div className="react-pop" role="menu">
              {EMOJIS.map((e) => (
                <button key={e} className="emoji" onClick={() => react(e)} aria-label={`React ${e}`}>{e}</button>
              ))}
            </div>
          )}
        </div>
        <button className={`ctl ${tab === "chat" ? "on" : ""}`} onClick={() => setTab("chat")} aria-label="Open chat">
          💬<span className="txt">{unread ? `Chat (${unread})` : "Chat"}</span>
        </button>
        <button className={`ctl ${captionsOn ? "on" : ""}`} onClick={() => setCaptionsOn((v) => !v)} aria-label="Toggle captions">
          CC<span className="txt">Captions</span>
        </button>
        <button className={`ctl ${voiceOn ? "on" : ""}`} onClick={() => setVoiceOn((v) => !v)} aria-label="Toggle translated voice">
          🔊<span className="txt">Voice</span>
        </button>
        <button className="ctl leave" onClick={leave} aria-label="Leave">Leave</button>
      </div>
    </div>
  );
}

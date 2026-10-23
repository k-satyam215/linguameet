"use client";

import { Participant as LKParticipant, Track } from "livekit-client";
import { useEffect, useRef } from "react";
import type { Lang } from "@/lib/api";
import type { Participant } from "@/lib/useTranslation";

type TileSpec = { key: string; p: LKParticipant; screen: boolean };

function Tile({
  spec, local, localName, info, langs, speaking, muteOriginal, hand, pinned, onPin,
}: {
  spec: TileSpec;
  local: boolean;
  localName: string;
  info?: Participant;
  langs: Lang[];
  speaking: boolean;
  muteOriginal: boolean;
  hand: boolean;
  pinned: boolean;
  onPin: () => void;
}) {
  const { p, screen } = spec;
  const vref = useRef<HTMLVideoElement>(null);
  const aref = useRef<HTMLAudioElement>(null);
  const source = screen ? Track.Source.ScreenShare : Track.Source.Camera;
  const vtrack = p.getTrackPublication(source)?.track;
  const atrack = screen || local ? undefined : p.getTrackPublication(Track.Source.Microphone)?.track;

  useEffect(() => {
    const el = vref.current;
    if (!el || !vtrack) return;
    vtrack.attach(el);
    return () => {
      vtrack.detach(el);
    };
  }, [vtrack]);

  // Set the level before attaching so source audio cannot leak at full volume on mount.
  useEffect(() => {
    const el = aref.current;
    if (!el || !atrack) return;
    el.volume = muteOriginal ? 0 : 1;
    atrack.attach(el);
    return () => {
      atrack.detach(el);
    };
  }, [atrack, muteOriginal]);

  const name = p.name || (local ? localName : "") || p.identity;
  const speak = langs.find((l) => l.code === info?.speak)?.name;
  const listen = langs.find((l) => l.code === info?.listen)?.name;

  return (
    <div className={`tile ${speaking && !screen ? "speaking" : ""}`}>
      {vtrack ? (
        <video
          ref={vref}
          autoPlay
          playsInline
          muted={local || screen}
          style={{ transform: local && !screen ? "scaleX(-1)" : undefined, objectFit: screen ? "contain" : "cover" }}
        />
      ) : (
        <div className="avatar"><span>{name.slice(0, 1).toUpperCase()}</span></div>
      )}
      {!screen && !local && <audio ref={aref} autoPlay />}
      <div className="label">{screen ? `${name} — screen` : `${name}${local ? " (You)" : ""}`}</div>
      {hand && !screen && <div className="hand" title="Hand raised">✋</div>}
      {!screen && speak && <div className="lang pill">{speak} → {listen}</div>}
      <button className="pin" onClick={onPin} aria-label={pinned ? "Unpin" : "Pin"} title={pinned ? "Unpin" : "Pin to spotlight"}>
        {pinned ? "📌 Unpin" : "📍"}
      </button>
    </div>
  );
}

export function VideoGrid({
  participants, local, localName, roster, langs, activeSpeakers, muteOriginal, hands, pinned, onPin,
}: {
  participants: LKParticipant[];
  local: LKParticipant;
  localName: string;
  roster: Participant[];
  langs: Lang[];
  activeSpeakers: string[];
  muteOriginal: boolean;
  hands: string[];
  pinned: string | null;
  onPin: (key: string | null) => void;
}) {
  const all = [local, ...participants];
  const tiles: TileSpec[] = [
    ...all.filter((p) => p.getTrackPublication(Track.Source.ScreenShare)?.track).map((p) => ({ key: `${p.identity}-s`, p, screen: true })),
    ...all.map((p) => ({ key: `${p.identity}-c`, p, screen: false })),
  ];

  // Spotlight: an explicit pin wins; otherwise a screen share is spotlighted automatically.
  const explicit = pinned && tiles.some((t) => t.key === pinned) ? pinned : null;
  const focusKey = explicit ?? tiles.find((t) => t.screen)?.key ?? null;

  const render = (t: TileSpec) => (
    <Tile
      key={t.key}
      spec={t}
      local={t.p === local}
      localName={localName}
      info={roster.find((r) => r.identity === t.p.identity)}
      langs={langs}
      speaking={activeSpeakers.includes(t.p.identity)}
      muteOriginal={muteOriginal}
      hand={hands.includes(t.p.identity)}
      pinned={explicit === t.key}
      onPin={() => onPin(explicit === t.key ? null : t.key)}
    />
  );

  if (focusKey && tiles.length > 1) {
    const main = tiles.find((t) => t.key === focusKey)!;
    const rest = tiles.filter((t) => t.key !== focusKey);
    return (
      <div className="spot">
        <div className="spot-main">{render(main)}</div>
        <div className="spot-strip">{rest.map(render)}</div>
      </div>
    );
  }

  const n = tiles.length;
  const cols = n <= 1 ? 1 : n <= 4 ? 2 : n <= 9 ? 3 : 4;
  return (
    <div className="grid" style={{ ["--cols" as string]: cols }}>
      {tiles.map(render)}
    </div>
  );
}

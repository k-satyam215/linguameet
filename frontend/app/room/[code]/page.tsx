"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Meeting from "@/components/Meeting";
import PreJoin, { JoinSelection } from "@/components/PreJoin";
import { FALLBACK_LANGS, JoinInfo, Lang, fetchLanguages, joinRoom } from "@/lib/api";

type Saved = { room: string; name: string; speak: string; listen: string };

export default function RoomPage() {
  const router = useRouter();
  const params = useParams<{ code: string }>();
  const code = decodeURIComponent(params.code);
  const [langs, setLangs] = useState<Lang[]>(FALLBACK_LANGS);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState("");
  const [session, setSession] = useState<{ join: JoinInfo; sel: JoinSelection } | null>(null);

  useEffect(() => {
    let s: Saved | null = null;
    try {
      s = JSON.parse(sessionStorage.getItem("lm.join") || "null");
    } catch {}
    if (!s || s.room !== code) {
      router.replace(`/?room=${encodeURIComponent(code)}`);
      return;
    }
    setSaved(s);
    fetchLanguages().then(setLangs);
  }, [code, router]);

  const onJoin = async (sel: JoinSelection) => {
    setError("");
    setJoining(true);
    try {
      const join = await joinRoom({ room: code, name: sel.name, speak: sel.speak, listen: sel.listen });
      try {
        localStorage.setItem("lm.profile", JSON.stringify({ name: sel.name, speak: sel.speak, listen: sel.listen }));
      } catch {}
      setSession({ join, sel });
    } catch (e: any) {
      setError(e?.message || "Could not join. Is the API running?");
      setJoining(false);
    }
  };

  if (session) {
    const { join, sel } = session;
    return (
      <Meeting
        code={code}
        name={sel.name}
        join={join}
        langs={langs}
        initialSpeak={sel.speak}
        initialListen={sel.listen}
        initialMicOn={sel.micOn}
        initialCamOn={sel.camOn}
        micId={sel.micId}
        camId={sel.camId}
        onLeave={() => router.push("/")}
      />
    );
  }
  if (!saved) {
    return (
      <main className="lobby">
        <div className="hint">Loading…</div>
      </main>
    );
  }
  return (
    <PreJoin
      code={code}
      langs={langs}
      initial={{ name: saved.name, speak: saved.speak, listen: saved.listen }}
      busy={joining}
      error={error}
      onJoin={onJoin}
      onBack={() => router.push("/")}
    />
  );
}

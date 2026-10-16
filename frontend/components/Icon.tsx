import type { ReactNode } from "react";

export type IconName =
  | "mic" | "camera" | "share" | "hand" | "smile" | "chat"
  | "captions" | "volume" | "leave" | "lock" | "mute" | "link"
  | "globe" | "spark" | "arrow";

const shapes: Record<IconName, ReactNode> = {
  mic: <><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3m-4 0h8" /></>,
  camera: <><rect x="3" y="6.5" width="13" height="11" rx="2.5" /><path d="m16 10 5-3v10l-5-3z" /></>,
  share: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8m-4-4v4m-3-11 3-3 3 3m-3-3v8" /></>,
  hand: <><path d="M8 12V6a1.5 1.5 0 0 1 3 0v5-7a1.5 1.5 0 0 1 3 0v7-5a1.5 1.5 0 0 1 3 0v7-3a1.5 1.5 0 0 1 3 0v5c0 4-2.5 7-6.5 7h-1c-2 0-3.5-1-4.5-2.5L5 15a1.7 1.7 0 0 1 2.5-2.2L8 13" /></>,
  smile: <><circle cx="12" cy="12" r="9" /><path d="M8.5 14.5s1.2 2 3.5 2 3.5-2 3.5-2M9 9h.01M15 9h.01" /></>,
  chat: <><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-6.5A7.5 7.5 0 1 1 20 11.5Z" /><path d="M8 11h8m-8 3h5" /></>,
  captions: <><rect x="2.5" y="5" width="19" height="14" rx="3" /><path d="M10 10a2.5 2.5 0 1 0 0 4m7-4a2.5 2.5 0 1 0 0 4" /></>,
  volume: <><path d="M4 10v4h4l5 4V6l-5 4H4Z" /><path d="M17 9a4 4 0 0 1 0 6m2-9a8 8 0 0 1 0 12" /></>,
  leave: <><path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5m4-4 4-4-4-4m4 4H9" /></>,
  lock: <><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2" /></>,
  mute: <><path d="M4 10v4h4l5 4V6l-5 4H4Z" /><path d="m17 9 5 6m0-6-5 6" /></>,
  link: <><path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7.1-7.1l-1.2 1.2" /><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7.1 7.1l1.2-1.2" /></>,
  globe: <><circle cx="12" cy="12" r="9" /><path d="M3.5 12h17M12 3a14 14 0 0 1 0 18m0-18a14 14 0 0 0 0 18" /></>,
  spark: <><path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5L12 3Zm7 12 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" /></>,
  arrow: <><path d="M4 12h15m-6-6 6 6-6 6" /></>,
};

export default function Icon({ name, className }: { name: IconName; className?: string }) {
  return <svg aria-hidden="true" className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{shapes[name]}</svg>;
}

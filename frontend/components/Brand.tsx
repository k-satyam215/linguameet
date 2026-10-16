export default function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "brand-lockup brand-compact" : "brand-lockup"} aria-label="LinguaMeet">
      <span className="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 48 48" fill="none">
          <defs>
            <linearGradient id="linguameet-mark" x1="6" y1="5" x2="42" y2="43" gradientUnits="userSpaceOnUse">
              <stop stopColor="#5D74F5" />
              <stop offset="1" stopColor="#25B99B" />
            </linearGradient>
          </defs>
          <rect x="2" y="2" width="44" height="44" rx="15" fill="url(#linguameet-mark)" />
          <path d="M10 17.5c0-3 2.5-5.5 5.5-5.5h11c3 0 5.5 2.5 5.5 5.5v5c0 3-2.5 5.5-5.5 5.5h-6l-6.5 5v-6A5.5 5.5 0 0 1 10 22.5v-5Z" fill="white" fillOpacity=".98" />
          <path d="M17 19h8m-8 4h5" stroke="#526CE0" strokeWidth="2" strokeLinecap="round" />
          <path d="M27 28.5h5.5c2.5 0 4.5 2 4.5 4.5v1l3 3h-7.5c-2.5 0-4.5-2-4.5-4.5v-1" fill="#D9FFF3" />
          <circle cx="34.5" cy="31" r="1" fill="#159C82" />
        </svg>
      </span>
      <span className="brand-copy">
        <span className="brand-name">Lingua<span>Meet</span></span>
        {!compact && <span className="brand-caption">MEET BEYOND LANGUAGE</span>}
      </span>
    </div>
  );
}

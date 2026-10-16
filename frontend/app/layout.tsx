import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  applicationName: "LinguaMeet",
  title: {
    default: "LinguaMeet — Every voice, understood",
    template: "%s | LinguaMeet",
  },
  description: "Video meetings with live translated captions and optional spoken translation.",
  openGraph: {
    title: "LinguaMeet — Every voice, understood",
    description: "Speak naturally. Follow every conversation in your language.",
    siteName: "LinguaMeet",
    type: "website",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f5f7fb",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

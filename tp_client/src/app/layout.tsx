import type { Metadata } from "next";
import { Karla, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// shadcn's globals.css resolves font-sans through --font-sans, not create-next-app's
// --font-geist-sans, so naming it here is what stops the page falling back to serif.
const karla = Karla({
  variable: "--font-sans",
  subsets: ["latin"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  weight: ["400", "500"],
  subsets: ["latin"],
});

const GRAIN =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='180' height='180' filter='url(%23g)' opacity='0.13'/%3E%3C/svg%3E\")";

export const metadata: Metadata = {
  title: "Plan a city trip",
  description: "We read real travel videos to find places worth going to.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${karla.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
        <div
          aria-hidden
          className="pointer-events-none fixed inset-0 z-60 opacity-40 mix-blend-multiply"
          style={{ backgroundImage: GRAIN }}
        />
      </body>
    </html>
  );
}

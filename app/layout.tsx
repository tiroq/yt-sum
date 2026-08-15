import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "YT Sum — Local YouTube Intelligence",
  description: "Slow, respectful transcript collection and local-first video summaries.",
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ru"><body>{children}</body></html>;
}


import type { Metadata } from "next";
import { Inter, Outfit, Fraunces } from "next/font/google";
import SmoothScroll from "@/components/layout/SmoothScroll";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-outfit",
  display: "swap",
});

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  style: ["normal", "italic"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "HIE — Human Intelligence Engine",
  description:
    "HIE combats cognitive decline and 7-second attention spans by transforming passive learning into an AI Tutor that monitors and prompts to build IQ, EQ, and Critical Thinking.",
  keywords: [
    "Human Intelligence Engine",
    "HIE",
    "cognitive reasoning",
    "AI tutor",
    "attention span",
    "critical thinking",
  ],
  openGraph: {
    title: "HIE — Human Intelligence Engine",
    description:
      "A solution to mature analytical reasoning degraded by technological marketing. An AI Tutor that dynamically prompts and evaluates concentration.",
    type: "website",
    locale: "en_US",
    siteName: "HIE",
  },
  twitter: {
    card: "summary_large_image",
    title: "HIE — Human Intelligence Engine",
    description:
      "Combat cognitive decline. Mature your analytical reasoning with the Human Intelligence Engine.",
  },
};

import MouseAmbientGlow from "@/components/ui/MouseAmbientGlow";
import { AuthProvider } from "@/contexts/AuthContext";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${outfit.variable} ${fraunces.variable} h-full antialiased`}
      data-scroll-behavior="smooth"
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col font-sans">
        <AuthProvider>
          <MouseAmbientGlow />
          <SmoothScroll>{children}</SmoothScroll>
        </AuthProvider>
      </body>
    </html>
  );
}

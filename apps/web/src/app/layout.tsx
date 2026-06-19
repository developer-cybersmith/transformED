import type { Metadata } from "next";
import { Inter, Outfit } from "next/font/google";
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

export const metadata: Metadata = {
  title: "TransformED — Turn Any PDF into an Immersive AI Learning Experience",
  description:
    "TransformED uses AI to transform your educational PDFs into interactive, guided lessons with personalized tutoring, quizzes, and teach-back exercises.",
  keywords: [
    "AI learning",
    "PDF to lessons",
    "educational AI",
    "personalized learning",
    "AI tutor",
    "interactive education",
  ],
  openGraph: {
    title: "TransformED — AI-Powered Learning from Any PDF",
    description:
      "Upload any PDF. Get an immersive, AI-guided learning experience with personalized tutoring and interactive lessons.",
    type: "website",
    locale: "en_US",
    siteName: "TransformED",
  },
  twitter: {
    card: "summary_large_image",
    title: "TransformED — AI-Powered Learning from Any PDF",
    description:
      "Upload any PDF. Get an immersive, AI-guided learning experience.",
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
      className={`${inter.variable} ${outfit.variable} h-full antialiased`}
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

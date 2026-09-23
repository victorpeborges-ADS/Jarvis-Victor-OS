import type { Metadata } from "next";
import { Inter, Newsreader } from "next/font/google";
import "./globals.css";
import { Header } from "@/components/ui/Header";
import { BottomNav } from "@/components/ui/BottomNav";
import { Sidebar } from "@/components/ui/Sidebar";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap"
});

const newsreader = Newsreader({
  subsets: ["latin"],
  variable: "--font-newsreader",
  display: "swap"
});

export const metadata: Metadata = {
  title: "JARVIS — Victor OS",
  description: "Victor OS + Victor Context Hub — protótipo Gate 1 com dados DEMO fictícios"
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover" as const
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={`${inter.variable} ${newsreader.variable}`}>
      <body className="min-h-screen bg-paper font-sans antialiased">
        <a
          href="#conteudo"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-ink focus:px-4 focus:py-2 focus:text-white"
        >
          Pular para o conteúdo
        </a>
        <Header />
        <div className="mx-auto flex max-w-[1280px]">
          <Sidebar />
          <main id="conteudo" className="main-with-bottom-nav min-h-[calc(100vh-64px)] flex-1">
            <div className="animate-fadeIn">{children}</div>
          </main>
        </div>
        <BottomNav />
      </body>
    </html>
  );
}

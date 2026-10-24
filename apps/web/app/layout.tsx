import type { Metadata } from "next";
import "./globals.css";
import { Header } from "@/components/ui/Header";
import { BottomNav } from "@/components/ui/BottomNav";
import { Sidebar } from "@/components/ui/Sidebar";
import { LocalIntegrationProvider } from "@/components/integration/LocalIntegrationProvider";

export const metadata: Metadata = {
  title: "JARVIS — Victor OS",
  description: "JARVIS — assistente pessoal em demonstração com informações de exemplo"
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover" as const
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-paper font-sans antialiased">
        <a
          href="#conteudo"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-ink focus:px-4 focus:py-2 focus:text-white"
        >
          Pular para o conteúdo
        </a>
        <LocalIntegrationProvider>
          <Header />
          <div className="mx-auto flex max-w-[1280px]">
            <Sidebar />
            <main id="conteudo" className="main-with-bottom-nav min-h-[calc(100vh-64px)] flex-1">
              <div className="animate-fadeIn">{children}</div>
            </main>
          </div>
          <BottomNav />
        </LocalIntegrationProvider>
      </body>
    </html>
  );
}

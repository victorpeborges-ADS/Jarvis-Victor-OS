import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px-var(--bottom-nav-height))] max-w-[560px] flex-col items-start justify-center px-4 py-16 md:min-h-[calc(100vh-64px)] md:px-8">
      <div className="text-xs font-semibold tracking-widest text-ink-faint">JARVIS · VICTOR OS</div>
      <p className="mt-3 text-sm font-medium text-ink-subtle">Página não encontrada</p>
      <h1 className="prose-editorial mt-2 text-[40px] font-medium leading-none tracking-tight text-ink md:text-[48px]">404</h1>
      <p className="mt-4 max-w-[420px] text-sm leading-relaxed text-ink-muted">
        Este endereço não existe neste protótipo Gate 1. Os dados continuam DEMO — nada foi perdido.
      </p>
      <div className="mt-8 flex flex-wrap gap-2">
        <Link
          href="/"
          className="inline-flex items-center justify-center rounded-full bg-ink px-5 py-2.5 text-sm font-medium text-white hover:bg-action-hover"
        >
          Voltar ao Agora
        </Link>
        <Link
          href="/conversa"
          className="inline-flex items-center justify-center rounded-full border border-paper-border bg-white px-5 py-2.5 text-sm font-medium text-ink hover:bg-paper-muted"
        >
          Perguntar ao JARVIS
        </Link>
        <Link
          href="/fontes"
          className="inline-flex items-center justify-center rounded-full border border-paper-border bg-white px-5 py-2.5 text-sm font-medium text-ink hover:bg-paper-muted"
        >
          Fontes e privacidade
        </Link>
      </div>
      <p className="mt-10 text-xs text-ink-faint">Gate 1 · simulação · sem OAuth real</p>
    </div>
  );
}

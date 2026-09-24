"use client";
import Link from "next/link";
import { useState } from "react";
import { usePathname } from "next/navigation";

export function Header() {
  const [open, setOpen] = useState(false);
  const integrated = usePathname() === "/integrado";
  return (
    <header className="sticky top-0 z-40 border-b border-paper-border bg-paper-elevated/80 backdrop-blur">
      <div className="mx-auto flex h-[64px] max-w-[1280px] items-center justify-between gap-4 px-4 md:px-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-3 rounded-lg ">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-[11px] font-semibold tracking-widest text-white">
              JVS
            </div>
            <div className="hidden md:block">
              <div className="text-sm font-semibold tracking-tight text-ink">JARVIS</div>
              <div className=" -mt-1 text-[11px] font-medium tracking-widest text-ink-subtle">{integrated ? "API LOCAL · SIMULADA" : "VICTOR OS · DEMO"}</div>
            </div>
          </Link>
          <span className="hidden h-6 w-px bg-paper-border md:block" aria-hidden />
          <span className="hidden items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800 md:inline-flex">
            <span className="h-2 w-2 rounded-full bg-amber-500" aria-hidden />
            {integrated ? "Gate 2 · sintético" : "Gate 1 · mock"}
          </span>
        </div>

        <div className="flex flex-1 justify-center px-2 md:px-8">
          {integrated ? (
            <div className="w-full max-w-[560px] rounded-full border border-paper-border bg-paper-muted px-4 py-2.5 text-center text-xs text-ink-subtle">
              Conversa e priorização não estão ativas no modo sintético
            </div>
          ) : (
            <button
              onClick={() => setOpen((v) => !v)}
              className="flex w-full max-w-[560px] items-center gap-3 rounded-full border border-paper-border bg-paper-muted px-4 py-2.5 text-left text-sm text-ink-subtle shadow-sm transition hover:border-ink-faint hover:bg-white "
              aria-label="Perguntar ao JARVIS — comando universal"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                <path d="M7.333 12.667A5.333 5.333 0 1 0 7.333 2a5.333 5.333 0 0 0 0 10.667Z" stroke="currentColor" strokeWidth="1.3" />
                <path d="M11.333 11.333 13.333 13.333" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              </svg>
              <span className="hidden sm:inline">Perguntar ao JARVIS — “O que mudou? Tenho 45 min…”</span>
              <span className="sm:hidden">Perguntar…</span>
              <span className="ml-auto hidden items-center gap-1 rounded-full bg-white px-2 py-1 text-xs font-medium text-ink-faint shadow-sm ring-1 ring-paper-border md:inline-flex">
                ⌘K
              </span>
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Link href={integrated ? "/" : "/integrado"} aria-label={integrated ? "Mudar para modo DEMO" : "Abrir integração sintética com API local"}
            className="inline-flex items-center rounded-full border border-paper-border bg-white px-3 py-2 text-xs font-semibold text-ink transition hover:bg-paper-muted">
            {integrated ? "DEMO" : "API local"}
          </Link>
          {!integrated && <Link
            href="/inbox"
            className="inline-flex items-center gap-2 rounded-full bg-ink px-4 py-2 text-sm font-medium text-white transition hover:bg-action-hover "
          >
            <span aria-hidden>+</span> Captura rápida
          </Link>}
          <div className="hidden h-8 w-8 items-center justify-center rounded-full bg-paper-muted text-xs font-semibold text-ink-muted md:flex" aria-hidden>
            V
          </div>
        </div>
      </div>

      {/* Mock command palette */}
      {open && !integrated && (
        <div className="border-t border-paper-border bg-white px-4 py-4 md:px-6">
          <div className="mx-auto max-w-[560px] rounded-2xl border border-paper-border bg-paper-muted p-3 shadow-soft">
            <div className="px-2 py-1 text-xs font-medium tracking-widest text-ink-faint">SUGESTÕES CONTEXTUAIS — DEMO</div>
            <div className="mt-2 space-y-1">
              {["Resumir o dia com evidências", "Mostrar conflito Academia × MedSyn", "Capturar ideia sobre CRIVO"].map((s) => (
                <button
                  key={s}
                  className="w-full rounded-xl bg-white px-3 py-2.5 text-left text-sm text-ink transition hover:bg-ink hover:text-white"
                  onClick={() => setOpen(false)}
                >
                  {s}
                </button>
              ))}
            </div>
            <div className="mt-3 flex items-center gap-2 px-2 text-xs text-ink-subtle">
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-paper-border text-[10px]">🎙</span>
              Voz — paridade com texto, placeholder honesto (Gate 5)
            </div>
          </div>
        </div>
      )}
    </header>
  );
}

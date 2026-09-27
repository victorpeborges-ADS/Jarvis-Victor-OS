"use client";
import Link from "next/link";
import { useState } from "react";
import { usePathname } from "next/navigation";
import { Dialog } from "./Dialog";

const items = [
  { href: "/", label: "Agora", icon: "◐" },
  { href: "/conversa", label: "Perguntar", icon: "✦" },
  { href: "/missoes", label: "Missões", icon: "◎" },
  { href: "/aprovacoes", label: "Aprovações", ariaLabel: "Aprovações", icon: "✓" }
];
const moreItems = [
  { href: "/inbox", label: "Caixa de entrada", detail: "Registre uma ideia ou referência" },
  { href: "/dominios", label: "Domínios", detail: "Veja informações por área" },
  { href: "/fontes", label: "Fontes e privacidade", detail: "Confira a origem dos dados" },
  { href: "/integrado", label: "Integração local", detail: "Sessão e permissões deste aparelho" }
];

export function BottomNav() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  const moreActive = moreItems.some((item) => pathname === item.href);
  return (
    <><nav
      aria-label="Navegação mobile"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-paper-border bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80 md:hidden"
      style={{
        height: "calc(var(--bottom-nav-height) + env(safe-area-inset-bottom, 0px))",
        paddingBottom: "env(safe-area-inset-bottom, 0px)"
      }}
    >
      <div className="grid h-[var(--bottom-nav-height)] grid-cols-5 gap-1 px-1">
        {items.map((it) => {
          const active = pathname === it.href || (it.href !== "/" && pathname.startsWith(it.href));
          return (
            <Link
              key={it.href}
              href={it.href}
              aria-label={it.ariaLabel ?? it.label}
              aria-current={active ? "page" : undefined}
              className={[
                "flex min-h-[44px] flex-col items-center justify-center rounded-xl px-1 py-1.5 text-xs transition ",
                active ? "bg-ink text-white" : "text-ink-subtle hover:bg-paper-muted"
              ].join(" ")}
            >
              <span aria-hidden className="text-lg leading-none">
                {it.icon}
              </span>
              <span className="mt-1 break-words text-center text-xs font-semibold leading-none tracking-tight">{it.label}</span>
            </Link>
          );
        })}
        <button type="button" aria-expanded={moreOpen} aria-haspopup="dialog" onClick={() => setMoreOpen(true)}
          className={["flex min-h-[44px] flex-col items-center justify-center rounded-xl px-1 py-1.5 text-xs transition",
            moreActive ? "bg-ink text-white" : "text-ink-subtle hover:bg-paper-muted"].join(" ")}>
          <span aria-hidden className="text-lg leading-none">⋯</span><span className="mt-1 text-xs font-semibold leading-none">Mais</span>
        </button>
      </div>
    </nav>
    <Dialog open={moreOpen} onClose={() => setMoreOpen(false)} titleId="more-nav-title" label="Mais áreas do JARVIS">
      <div className="flex items-center justify-between border-b border-paper-border p-5">
        <h2 id="more-nav-title" className="text-xl font-semibold text-ink">Mais áreas</h2>
        <button type="button" onClick={() => setMoreOpen(false)} className="min-h-11 min-w-11 rounded-lg px-3 py-2 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-action">Fechar</button>
      </div>
      <div className="grid gap-2 p-5">{moreItems.map((item) => <Link key={item.href} href={item.href}
        onClick={() => setMoreOpen(false)}
        className="rounded-xl border border-paper-border p-4 text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-action">
        <span className="block text-base font-semibold">{item.label}</span><span className="mt-1 block text-sm text-ink-subtle">{item.detail}</span>
      </Link>)}</div>
    </Dialog></>
  );
}

"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "Agora", desc: "Visão do momento", icon: "◐" },
  { href: "/conversa", label: "Conversa", desc: "Perguntar ao JARVIS", icon: "✦" },
  { href: "/inbox", label: "Inbox", desc: "Captura rápida", icon: "▭" },
  { href: "/dominios", label: "Domínios", desc: "Filtros de vida", icon: "⬡" },
  { href: "/aprovacoes", label: "Aprovações", desc: "Fila explícita", icon: "✓" },
  { href: "/fontes", label: "Fontes", desc: "Privacidade", icon: "⬢" }
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="hidden w-[240px] shrink-0 border-r border-paper-border bg-paper-elevated md:block">
      <nav className="sticky top-[64px] p-3" aria-label="Navegação principal">
        <div className="space-y-1">
          {items.map((it) => {
            const active = pathname === it.href || (it.href !== "/" && pathname.startsWith(it.href));
            return (
              <Link
                key={it.href}
                href={it.href}
                aria-current={active ? "page" : undefined}
                className={[
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition focus-visible:outline-none",
                  active ? "bg-ink text-white shadow-sm" : "text-ink-muted hover:bg-paper-muted hover:text-ink"
                ].join(" ")}
              >
                <span className={["flex h-7 w-7 items-center justify-center rounded-lg text-xs", active ? "bg-white/15 text-white" : "bg-paper-muted"].join(" ")} aria-hidden>
                  {it.icon}
                </span>
                <span className="flex flex-col">
                  <span className="font-medium leading-none">{it.label}</span>
                  <span className={["text-xs leading-none", active ? "text-white/70" : "text-ink-faint"].join(" ")}>{it.desc}</span>
                </span>
              </Link>
            );
          })}
        </div>

        <div className="mt-6 rounded-2xl border border-paper-border bg-paper-muted p-4">
          <div className="text-xs font-semibold tracking-widest text-ink-faint">ESTADO — GATE 1</div>
          <div className="mt-2 space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-ink-subtle">Calendar</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-1 font-medium text-emerald-700 ring-1 ring-emerald-200">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> connected
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-ink-subtle">Gmail</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-1 font-medium text-emerald-700 ring-1 ring-emerald-200">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> connected
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-ink-subtle">Drive</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2 py-1 font-medium text-amber-700 ring-1 ring-amber-200" title="Sem sincronização há 24h">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500" /> stale
              </span>
            </div>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-ink-faint">Dados mock sinalizados. Nenhuma escrita externa sem aprovação explícita.</p>
        </div>

        <div className="mt-4 rounded-xl bg-amber-50 px-3 py-3 ring-1 ring-amber-200">
          <div className="text-xs font-semibold text-amber-800">DEMO</div>
          <p className="mt-1 text-xs leading-relaxed text-amber-700">Tudo aqui é fictício. Veja fontes para proveniência.</p>
        </div>
      </nav>
    </aside>
  );
}

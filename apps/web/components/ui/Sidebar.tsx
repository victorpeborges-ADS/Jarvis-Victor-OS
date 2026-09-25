"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { fixtures, syncStatusLabel, providerLabel, formatTimeH } from "@/lib/demo";
import { ConnectorBadge } from "@/components/ui/primitives";

const items = [
  { href: "/", label: "Agora", desc: "Visão do momento", icon: "◐" },
  { href: "/conversa", label: "Conversa", desc: "Perguntar ao JARVIS", icon: "✦" },
  { href: "/inbox", label: "Inbox", desc: "Captura rápida", icon: "▭" },
  { href: "/dominios", label: "Domínios", desc: "Filtros de vida", icon: "⬡" },
  { href: "/missoes", label: "Missões", desc: "Execução sintética", icon: "◎" },
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
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition ",
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

        <Link href={pathname === "/integrado" ? "/" : "/integrado"}
          className="mt-5 flex items-center justify-between rounded-xl border border-violet-200 bg-violet-50 px-3 py-3 text-sm font-medium text-violet-950 hover:bg-violet-100">
          <span>{pathname === "/integrado" ? "Voltar ao modo DEMO" : "Integração sintética"}</span>
          <span aria-hidden>↔</span>
        </Link>

        {pathname === "/integrado" ? (
          <div className="mt-4 rounded-xl border border-violet-200 bg-white px-3 py-3">
            <div className="text-xs font-semibold tracking-wide text-violet-900">API LOCAL · SIMULAÇÃO</div>
            <p className="mt-1 text-xs leading-relaxed text-ink-subtle">Provider Calendar fictício. Nenhuma conta Google está conectada.</p>
          </div>
        ) : <div className="mt-6 rounded-2xl border border-paper-border bg-paper-muted p-4">
          <div className="text-xs font-semibold tracking-widest text-ink-faint">CONECTORES — GATE 1</div>
          <div className="mt-2 space-y-2 text-xs">
            {fixtures.sources.map((s) => (
              <div key={s.id} className="flex items-center justify-between gap-2">
                <span className="text-ink-subtle">{providerLabel(s.provider).replace("Google ", "")}</span>
                <ConnectorBadge status={s.sync_status} label={syncStatusLabel(s.sync_status)} />
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs leading-relaxed text-ink-faint">
            Simulação sinalizada. Última verificação mock: {formatTimeH(fixtures.sources[0].last_success)}. Sem escrita externa.
          </p>
        </div>}

        <div className="mt-4 rounded-xl bg-amber-50 px-3 py-3 ring-1 ring-amber-200">
          <div className="text-xs font-semibold text-amber-800">DEMO</div>
          <p className="mt-1 text-xs leading-relaxed text-amber-700">Tudo aqui é fictício. Veja Fontes para proveniência.</p>
        </div>
      </nav>
    </aside>
  );
}

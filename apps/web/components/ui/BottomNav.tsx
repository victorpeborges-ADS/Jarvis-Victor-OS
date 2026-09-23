"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "Agora", icon: "◐" },
  { href: "/conversa", label: "JARVIS", icon: "✦" },
  { href: "/inbox", label: "Inbox", icon: "▭" },
  { href: "/dominios", label: "Domínios", icon: "⬡" },
  { href: "/aprovacoes", label: "Aprovar", icon: "✓" }
];

export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Navegação mobile"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-paper-border bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80 md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="grid grid-cols-5 gap-1 px-2 py-2">
        {items.map((it) => {
          const active = pathname === it.href;
          return (
            <Link
              key={it.href}
              href={it.href}
              aria-current={active ? "page" : undefined}
              className={[
                "flex flex-col items-center justify-center rounded-xl px-2 py-1.5 text-xs transition focus-visible:outline-none",
                active ? "bg-ink text-white" : "text-ink-subtle hover:bg-paper-muted"
              ].join(" ")}
            >
              <span aria-hidden className="text-sm leading-none">
                {it.icon}
              </span>
              <span className="mt-1 text-[11px] font-medium leading-none">{it.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

"use client";
import { useState } from "react";
import { fixtures, syncStatusLabel, providerLabel, formatTimeH, sensitivityLabel, DEMO_NOW } from "@/lib/demo";
import { Badge, Card, ConnectorBadge, StaleBanner } from "@/components/ui/primitives";
import Link from "next/link";

export default function FontesPage() {
  const [controlNotice, setControlNotice] = useState("");
  const stale = fixtures.sources.find((s) => s.sync_status === "stale");
  function exportExamples() {
    const blob = new Blob([JSON.stringify(fixtures, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "jarvis-dados-de-exemplo.json";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setControlNotice("Arquivo de exemplo exportado.");
  }
  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">ORIGEM · PRIVACIDADE</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Fontes e privacidade</h1>
          <p className="text-sm text-ink-subtle">Confira de onde vêm as informações e quando foram verificadas. Esta tela usa exemplos fictícios.</p>
        </div>
        <Badge tone="amber">Demonstração</Badge>
      </div>

      <Card className="mt-6 p-5">
        <h2 className="text-sm font-semibold text-ink">Estado das fontes de exemplo</h2>
        <p className="mt-1 text-xs text-ink-subtle">Nenhuma conta está conectada. Horário de referência: {formatTimeH(DEMO_NOW)}.</p>
        <div className="mt-3 grid gap-3 lg:grid-cols-3">
          {fixtures.sources.map((s) => (
            <div key={s.id} className="rounded-2xl border border-paper-border bg-paper-muted p-4">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs font-semibold tracking-widest text-ink-faint">{providerLabel(s.provider).toUpperCase()}</div>
                <ConnectorBadge status={s.sync_status} label={syncStatusLabel(s.sync_status)} />
              </div>
              <div className="mt-2 text-sm font-medium text-ink">{s.account}</div>
              <div className="mt-1 text-xs text-ink-subtle">Área: {s.scope}</div>
              <div className="mt-1 text-xs text-ink-faint">Última conferência: {formatTimeH(s.last_success)}</div>
              <div className="mt-2 text-xs text-ink-faint">Permissão: apenas ilustrativa</div>
            </div>
          ))}
        </div>
        <div className="mt-4 rounded-xl bg-ink px-4 py-3 text-xs leading-relaxed text-white/80">
          Estes estados ilustram como as fontes podem aparecer. Nenhuma conta foi conectada ou consultada.
        </div>
      </Card>

      {stale && (
        <div className="mt-4">
          <StaleBanner reason={`${providerLabel(stale.provider)}: ${stale.stale_reason}. As demais fontes de exemplo estão atualizadas no horário de referência.`} />
        </div>
      )}

      <Card className="mt-4 p-5">
        <h2 className="text-sm font-semibold text-ink">Origem de cada compromisso</h2>
        <div className="mt-3 space-y-3">
          {fixtures.events.map((ev) => (
          <div key={ev.id} className="rounded-2xl border border-paper-border bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-ink">{ev.title}</div>
                  <div className="mt-1 text-xs leading-relaxed text-ink-subtle">
                    Origem: {ev.provenance.origin} · Observado: {formatTimeH(ev.observed_at)} · Verificado: {formatTimeH(ev.provenance.last_checked)} · Confiança: {ev.provenance.confidence} · Área: {ev.provenance.scope}
                  </div>
                  <details className="mt-2 text-xs text-ink-faint">
                    <summary className="min-h-11 cursor-pointer py-3">IDs, endereço e validade</summary>
                    <p className="break-all">ID: {ev.id} · Fonte: {ev.source_id} · Referência: {ev.external_ref} · Validade: {"valid_until" in ev && typeof ev.valid_until === "string" ? formatTimeH(ev.valid_until) : "sem prazo informado"} · URL: {ev.provenance.url ?? "não informada"}</p>
                  </details>
                  {ev.provenance.note && <div className="mt-1 text-xs text-amber-700">{ev.provenance.note}</div>}
                </div>
                <Badge tone="slate">{sensitivityLabel(ev.sensitivity)}</Badge>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <h3 className="text-sm font-semibold text-ink">Privacidade por domínio</h3>
          <p className="mt-1 text-sm leading-relaxed text-ink-subtle">
            Separação: pessoal | empresarial/comercial | MedSyn | MCID. Sem cópia de docs restritos ou dados sensíveis de saúde para banco pessoal sem autorização.
          </p>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs leading-relaxed text-ink-subtle">
            <li>Um pedido pessoal não recupera docs institucionais protegidos.</li>
            <li>Logs sem PII.</li>
            <li>Preferir referência e metadados autorizados.</li>
          </ul>
        </Card>
        <Card className="p-5">
          <h3 className="text-sm font-semibold text-ink">Controle de dados</h3>
          <div className="mt-3 space-y-2">
            <button type="button" onClick={exportExamples} className="min-h-11 w-full rounded-xl border border-paper-border bg-paper-muted px-4 py-2.5 text-sm font-medium text-ink hover:bg-white">
              Exportar dados de exemplo (JSON)
            </button>
            <button type="button" onClick={() => setControlNotice("Pedido registrado nesta tela. Os exemplos fixos permanecem intactos; nenhum dado pessoal é armazenado aqui.")} className="min-h-11 w-full rounded-xl border border-paper-border bg-white px-4 py-2.5 text-sm font-medium text-ink hover:bg-paper-muted">
              Solicitar remoção dos dados de exemplo
            </button>
            <Link href="/" className="block w-full rounded-xl bg-ink px-4 py-2.5 text-center text-sm font-medium text-white hover:bg-action-hover">
              Voltar ao Agora
            </Link>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-ink-faint">Os exemplos desta tela são fixos e não contêm informações pessoais.</p>
          <p className="mt-3 min-h-6 text-sm text-ink-subtle" role="status" aria-live="polite">{controlNotice}</p>
        </Card>
      </div>
    </div>
  );
}

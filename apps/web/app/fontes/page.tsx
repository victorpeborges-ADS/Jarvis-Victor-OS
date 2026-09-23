import { fixtures, syncStatusLabel, providerLabel, formatTimeH, sensitivityLabel, DEMO_NOW } from "@/lib/demo";
import { Badge, Card, ConnectorBadge, StaleBanner } from "@/components/ui/primitives";
import Link from "next/link";

export default function FontesPage() {
  const stale = fixtures.sources.find((s) => s.sync_status === "stale");
  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">MEMÓRIA · ORIGENS · PRIVACIDADE</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Fontes e privacidade</h1>
          <p className="text-sm text-ink-subtle">Cada fato tem origem, verificação e escopo. Dados DEMO apenas.</p>
        </div>
        <Badge tone="amber">DEMO</Badge>
      </div>

      <Card className="mt-6 p-5">
        <h2 className="text-sm font-semibold text-ink">Estado dos conectores — Gate 1 (simulação)</h2>
        <p className="mt-1 text-xs text-ink-subtle">Nenhum status abaixo indica OAuth real. Relógio DEMO {formatTimeH(DEMO_NOW)}.</p>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {fixtures.sources.map((s) => (
            <div key={s.id} className="rounded-2xl border border-paper-border bg-paper-muted p-4">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs font-semibold tracking-widest text-ink-faint">{providerLabel(s.provider).toUpperCase()}</div>
                <ConnectorBadge status={s.sync_status} label={syncStatusLabel(s.sync_status)} />
              </div>
              <div className="mt-2 text-sm font-medium text-ink">{s.account}</div>
              <div className="mt-1 text-xs text-ink-subtle">Escopo: {s.scope}</div>
              <div className="mt-1 text-xs text-ink-faint">Última verificação (mock): {formatTimeH(s.last_success)}</div>
              <div className="mt-2 text-[11px] text-ink-faint">Consentimento: simulado</div>
            </div>
          ))}
        </div>
        <div className="mt-4 rounded-xl bg-ink px-4 py-3 text-xs leading-relaxed text-white/80">
          Sem OAuth real neste Gate. Status são <span className="font-semibold text-white">simulações sinalizadas</span>. Conexão real só no Gate 2 com conta pessoal autorizada.
        </div>
      </Card>

      {stale && (
        <div className="mt-4">
          <StaleBanner reason={`${providerLabel(stale.provider)}: ${stale.stale_reason}. As demais fontes simuladas estão ok neste relógio DEMO.`} />
        </div>
      )}

      <Card className="mt-4 p-5">
        <h2 className="text-sm font-semibold text-ink">Proveniência de cada evento</h2>
        <div className="mt-3 space-y-3">
          {fixtures.events.map((ev) => (
            <div key={ev.id} className="rounded-2xl border border-paper-border bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-ink">{ev.title}</div>
                  <div className="mt-1 text-xs text-ink-subtle">
                    Origem: {ev.provenance.origin} · Verificado: {formatTimeH(ev.provenance.last_checked)} · Confiança:{" "}
                    {ev.provenance.confidence} · Escopo: {ev.provenance.scope}
                  </div>
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
            <button type="button" className="w-full rounded-xl border border-paper-border bg-paper-muted px-4 py-2.5 text-sm font-medium text-ink hover:bg-white">
              Exportar fixtures (JSON)
            </button>
            <button type="button" className="w-full rounded-xl border border-paper-border bg-white px-4 py-2.5 text-sm font-medium text-ink hover:bg-paper-muted">
              Solicitar exclusão local (simulado)
            </button>
            <Link href="/" className="block w-full rounded-xl bg-ink px-4 py-2.5 text-center text-sm font-medium text-white hover:bg-action-hover">
              Voltar ao Agora
            </Link>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-ink-faint">Retenção e exclusão testadas apenas com dados DEMO.</p>
        </Card>
      </div>
    </div>
  );
}

"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Badge, Button, Card } from "@/components/ui/primitives";
import {
  SYNTHETIC_DOMAINS, useLocalIntegration, type SyntheticDomainId
} from "@/components/integration/LocalIntegrationProvider";
import type { CalendarSyncState, LocalGrant, SimulatedCalendar } from "@/lib/local-api";

function localDate(value: string | null | undefined): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "não disponível";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "medium", timeStyle: "short", timeZone: "America/Sao_Paulo"
  }).format(new Date(value));
}

function statusLabel(status: CalendarSyncState["status"] | undefined): string {
  if (status === "simulated") return "Simulação atualizada";
  if (status === "stale") return "Dados desatualizados";
  if (status === "error") return "Erro na sincronização";
  return "Não sincronizado";
}

function statusTone(status: CalendarSyncState["status"] | undefined): "emerald" | "amber" | "red" | "neutral" {
  if (status === "simulated") return "emerald";
  if (status === "stale") return "amber";
  if (status === "error") return "red";
  return "neutral";
}

function domainLabel(domainId: string | null | undefined): string {
  return SYNTHETIC_DOMAINS.find((domain) => domain.id === domainId)?.label ?? "sem classificação visível";
}

function hasResourceGrant(grants: LocalGrant[], domainId: string, resourceId: string): boolean {
  return grants.some((grant) => grant.domain_ids.includes(domainId) && grant.resource_ids.includes(resourceId) && !grant.revoked && Date.parse(grant.expires_at) > Date.now());
}

function hasDomainGrant(grants: LocalGrant[], domainId: string): boolean {
  return hasResourceGrant(grants, domainId, "calendar:synthetic-primary");
}

function LoginForm() {
  const { login, notice, clearNotice } = useLocalIntegration();
  const [passphrase, setPassphrase] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    clearNotice();
    try {
      await login(passphrase);
    } finally {
      setPassphrase("");
      setSubmitting(false);
    }
  }

  return (
    <Card className="mt-5 p-5 md:p-6">
      <h2 className="text-lg font-semibold text-ink">Entrar na integração local</h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-subtle">
        Use a frase de acesso configurada para este serviço local. Esta área trabalha apenas com dados de exemplo.
      </p>
      <details className="mt-2 text-xs text-ink-faint"><summary className="min-h-11 cursor-pointer py-3">Proteções técnicas</summary><p>A frase segue apenas para o serviço neste aparelho. A sessão usa cookie HttpOnly e a proteção contra envio cruzado mantém o token somente na memória desta aplicação.</p></details>
      <form className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={submit}>
        <label className="min-w-0 flex-1 text-sm font-medium text-ink">
          Frase de acesso local
          <input
            data-testid="local-passphrase"
            type="password"
            autoComplete="off"
            minLength={12}
            maxLength={200}
            required
            value={passphrase}
            onChange={(event) => setPassphrase(event.target.value)}
            className="mt-1.5 w-full rounded-xl border border-paper-border bg-white px-3 py-2.5 text-base text-ink outline-none focus-visible:ring-2 focus-visible:ring-action"
          />
        </label>
        <Button data-testid="local-login-submit" type="submit" disabled={submitting || passphrase.length < 12}>
          {submitting ? "Verificando…" : "Entrar"}
        </Button>
      </form>
      {notice && <p role="alert" className="mt-3 text-sm font-medium text-red-800">{notice}</p>}
    </Card>
  );
}

function GrantControls() {
  const { grants, createGrant, createInventoryGrant, revokeGrant, selectedDomain } = useLocalIntegration();
  const [domainId, setDomainId] = useState<SyntheticDomainId>(selectedDomain);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setLocalError(null);
    try { await createGrant(domainId); }
    catch { setLocalError("A concessão não foi criada. Confira a sessão e as permissões locais."); }
    finally { setBusy(false); }
  }

  async function grantInventory() {
    setBusy(true);
    setLocalError(null);
    try { await createInventoryGrant(domainId); }
    catch { setLocalError("O inventário limitado não foi concedido. Ele não autoriza leitura de eventos."); }
    finally { setBusy(false); }
  }

  async function revoke(grant: LocalGrant) {
    setBusy(true);
    setLocalError(null);
    try { await revokeGrant(grant); }
    catch { setLocalError("A concessão não foi revogada. Reautentique-se e tente novamente."); }
    finally { setBusy(false); }
  }

  return (
    <Card className="p-5 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-ink">Concessões locais</h2>
          <p className="mt-1 text-sm leading-relaxed text-ink-subtle">
            Leitura do catálogo fictício, restrita a um escopo sintético e válida por 7 dias. Nada é concedido automaticamente.
          </p>
        </div>
        <Badge tone="amber">somente leitura · simulado</Badge>
      </div>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex-1 text-sm font-medium text-ink">
          Escopo que você autoriza
          <select
            data-testid="grant-domain"
            value={domainId}
            onChange={(event) => setDomainId(event.target.value as SyntheticDomainId)}
            className="mt-1.5 w-full rounded-xl border border-paper-border bg-white px-3 py-2.5 text-sm text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action"
          >
            {SYNTHETIC_DOMAINS.map((domain) => <option key={domain.id} value={domain.id}>{domain.label}</option>)}
          </select>
        </label>
        <Button data-testid="grant-create" disabled={busy || hasDomainGrant(grants, domainId)} onClick={create}>
          {hasDomainGrant(grants, domainId) ? "Concessão ativa" : "Conceder leitura"}
        </Button>
        <Button data-testid="grant-inventory" variant="outline" disabled={busy || hasResourceGrant(grants, domainId, "calendar:synthetic-inventory")} onClick={() => void grantInventory()}>
          {hasResourceGrant(grants, domainId, "calendar:synthetic-inventory") ? "Inventário ativo" : "Conceder inventário limitado"}
        </Button>
      </div>
      {grants.length > 0 ? (
        <ul className="mt-4 space-y-2" aria-label="Concessões de leitura ativas">
          {grants.map((grant) => (
            <li key={grant.id} data-testid="grant-card" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-paper-border bg-paper-muted px-3 py-2.5">
              <div className="text-sm text-ink">
                <span className="font-medium">{grant.resource_ids.includes("calendar:synthetic-primary") ? "Calendar fictício" : grant.resource_ids.includes("calendar:synthetic-inventory") ? "Inventário limitado" : "Recurso simulado"}</span>
                <span className="text-ink-subtle"> · {grant.domain_ids.map(domainLabel).join(", ")} · até {localDate(grant.expires_at)}</span>
              </div>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void revoke(grant)} aria-label={`Revogar ${grant.resource_ids.includes("calendar:synthetic-primary") ? "leitura" : "inventário"} ${grant.domain_ids.map(domainLabel).join(", ")}`}>
                Revogar
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-ink-subtle">Nenhuma concessão ativa. Conceda leitura no escopo escolhido para consultar o catálogo sintético.</p>
      )}
      {grants.length > 0 && !grants.some((grant) => grant.resource_ids.includes("calendar:synthetic-primary") && !grant.revoked && Date.parse(grant.expires_at) > Date.now()) && (
        <p className="mt-3 text-sm text-ink-subtle">Conceda leitura no escopo escolhido para consultar o catálogo sintético. O inventário limitado não substitui essa leitura.</p>
      )}
      {localError && <p role="alert" className="mt-3 text-sm text-red-800">{localError}</p>}
    </Card>
  );
}

function CalendarCard({ calendar }: { calendar: SimulatedCalendar }) {
  const { grants, states, classifyCalendar, syncCalendar, selectedDomain } = useLocalIntegration();
  const [classification, setClassification] = useState<SyntheticDomainId>(selectedDomain);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const state = states.find((item) => item.calendar_id === calendar.calendar_id);
  const canClassify = hasDomainGrant(grants, classification) && (
    Boolean(state?.domain_id) || hasResourceGrant(grants, classification, "calendar:synthetic-inventory")
  );

  async function classify() {
    setBusy(true);
    setError(null);
    try { await classifyCalendar(calendar.calendar_id, classification); }
    catch { setError("Classificação recusada. O mapeamento exige concessão ativa e não é substituído automaticamente."); }
    finally { setBusy(false); }
  }

  async function sync() {
    setBusy(true);
    setError(null);
    try { await syncCalendar(calendar.calendar_id); }
    catch { setError("A sincronização simulada não foi concluída. O estado pode estar desatualizado; confira a API local."); }
    finally { setBusy(false); }
  }

  return (
    <Card data-testid="calendar-card" data-calendar-id={calendar.calendar_id} className="p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-ink">{calendar.name}</h3>
          <p className="mt-1 text-xs text-ink-subtle">Fuso {calendar.time_zone} · id sintético {calendar.calendar_id}</p>
        </div>
        <Badge tone={statusTone(state?.status)}>{statusLabel(state?.status)}</Badge>
      </div>
      <p className="mt-3 text-xs font-medium text-violet-800">Provedor inteiramente fictício · nenhuma conta Google conectada</p>
      {state ? (
        <div className="mt-3 rounded-lg bg-paper-muted px-3 py-2 text-sm text-ink-subtle">
          Classificação autorizada: <span className="font-medium text-ink">{domainLabel(state.domain_id)}</span>
          <div className="mt-1 text-xs">Última sincronização concluída: {localDate(state.last_success_at)}</div>
          {state.status === "error" && <div className="mt-1 text-xs text-red-800">Última tentativa: {localDate(state.last_attempt_at)}. Código técnico oculto.</div>}
          {state.status === "stale" && <div className="mt-1 text-xs text-amber-900">A última leitura passou do limite de 24 horas; ausência de eventos não indica agenda vazia.</div>}
        </div>
      ) : (
        <div className="mt-3 rounded-lg border border-dashed border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950">
          Em quarentena: sem classificação ou concessão ativa visível para este escopo.
        </div>
      )}
      {!state && (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="flex-1 text-xs font-medium text-ink-subtle">
            Classificar explicitamente em
            <select
              data-testid={`calendar-domain-${calendar.calendar_id}`}
              value={classification}
              onChange={(event) => setClassification(event.target.value as SyntheticDomainId)}
              className="mt-1 block w-full rounded-lg border border-paper-border bg-white px-3 py-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action"
            >
              {SYNTHETIC_DOMAINS.map((domain) => <option key={domain.id} value={domain.id}>{domain.label}</option>)}
            </select>
          </label>
          <Button size="sm" disabled={busy || !canClassify} onClick={() => void classify()} aria-label={`Classificar ${calendar.calendar_id}`}>
            Classificar calendário
          </Button>
        </div>
      )}
      {state && <Button className="mt-3" size="sm" disabled={busy || !hasDomainGrant(grants, state.domain_id ?? "")} onClick={() => void sync()} aria-label={`Sincronizar ${calendar.calendar_id}`}>
        {busy ? "Sincronizando…" : "Sincronizar simulação"}
      </Button>}
      {!canClassify && !state && <p className="mt-2 text-xs text-ink-subtle">Conceda leitura para o escopo escolhido antes de classificar.</p>}
      {error && <p role="alert" className="mt-2 text-sm text-red-800">{error}</p>}
    </Card>
  );
}

function IntegratedNow() {
  const {
    events, states, grants, selectedDomain, selectDomain, refreshEvents,
    eventsLoading, lastReport
  } = useLocalIntegration();
  const state = states.find((item) => item.domain_id === selectedDomain);
  const authorized = hasDomainGrant(grants, selectedDomain);
  const sortedEvents = events.slice().sort((a, b) => Date.parse(a.occurred_at ?? "") - Date.parse(b.occurred_at ?? ""));

  return (
    <section className="mt-6" aria-labelledby="integrated-now-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">AGORA · DADOS SINTÉTICOS DA API</div>
          <h2 id="integrated-now-title" className="prose-editorial mt-1 text-2xl font-medium text-ink">Agenda simulada</h2>
        </div>
        <label className="text-sm font-medium text-ink">
          Escopo de leitura
          <select
            data-testid="domain-filter"
            value={selectedDomain}
            onChange={(event) => void selectDomain(event.target.value as SyntheticDomainId)}
            className="mt-1 block w-full min-w-52 rounded-xl border border-paper-border bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action"
          >
            {SYNTHETIC_DOMAINS.map((domain) => <option key={domain.id} value={domain.id}>{domain.label}</option>)}
          </select>
        </label>
      </div>
      <div className="mt-3 rounded-xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm leading-relaxed text-violet-950">
        Eventos exibidos somente após autorização e classificação. Esta tela lista fatos cronologicamente; não há motor de priorização neste modo.
      </div>
      {state?.status === "stale" && <div role="status" className="mt-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
        Dados desatualizados: a última leitura foi em {localDate(state.last_success_at)}. A ausência de itens não confirma uma agenda vazia.
      </div>}
      {state?.status === "error" && <div role="alert" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
        A última sincronização simulada falhou ({localDate(state.last_attempt_at)}). Os itens persistidos podem refletir uma leitura anterior; o detalhe técnico foi ocultado.
      </div>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" disabled={!authorized || eventsLoading} onClick={() => void refreshEvents()}>
          {eventsLoading ? "Atualizando…" : "Atualizar eventos autorizados"}
        </Button>
        {state && <Badge tone={statusTone(state.status)}>{statusLabel(state.status)}</Badge>}
        {lastReport && <span className="text-xs text-ink-subtle">Último resultado: {lastReport.events_written} eventos gravados nesta simulação.</span>}
      </div>
      {!authorized ? (
        <div className="mt-4 rounded-xl border border-dashed border-amber-300 bg-amber-50 px-4 py-4 text-sm text-amber-950">
          Nenhum evento é consultado: ainda não há concessão ativa para {domainLabel(selectedDomain)}. A classificação sozinha não autoriza leitura.
        </div>
      ) : !state ? (
        <div className="mt-4 rounded-xl border border-dashed border-paper-border bg-paper-muted px-4 py-4 text-sm text-ink-subtle">
          Nenhum calendário classificado e sincronizado está visível neste escopo. Veja o estado de cada calendário abaixo; isso não afirma que não há compromissos.
        </div>
      ) : sortedEvents.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-paper-border bg-paper-muted px-4 py-4 text-sm text-ink-subtle">
          {state.status === "not_synced" ? "Ainda não houve sincronização; não é possível concluir que não há compromissos." : "A API não retornou eventos para este escopo. Confira a proveniência e o estado da fonte."}
        </div>
      ) : (
        <ul className="mt-4 space-y-3" data-testid="integrated-events">
          {sortedEvents.map((event) => (
            <li key={event.id} data-testid="local-event-card" data-domain-id={event.domain_id} className="rounded-2xl border border-paper-border bg-white p-4 md:p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="font-semibold leading-snug text-ink">{event.title}</h3>
                  <p className="mt-1 text-sm text-ink-subtle">{localDate(event.occurred_at)} · {event.calendar_name ?? "Calendário sintético"}</p>
                </div>
                <Badge tone="violet">simulado · {domainLabel(event.domain_id)}</Badge>
              </div>
              <details className="mt-3 border-t border-paper-border pt-2 text-xs text-ink-subtle">
                <summary className="cursor-pointer font-medium text-ink">Proveniência e verificação</summary>
                <dl className="mt-2 grid gap-1 sm:grid-cols-2">
                  <div><dt className="inline font-medium">Fonte: </dt><dd className="inline">Calendar inteiramente simulado</dd></div>
                  <div><dt className="inline font-medium">Referência externa sintética: </dt><dd className="inline break-all">{event.provenance.external_ref ?? "não disponível"}</dd></div>
                  <div><dt className="inline font-medium">Observado em: </dt><dd className="inline">{localDate(event.provenance.observed_at)}</dd></div>
                  <div><dt className="inline font-medium">Última verificação: </dt><dd className="inline">{localDate(event.provenance.last_verified_at)}</dd></div>
                  <div><dt className="inline font-medium">Classificação: </dt><dd className="inline">revisão humana explícita</dd></div>
                  <div><dt className="inline font-medium">Armazenamento: </dt><dd className="inline">Memória local isolada · conteúdo sintético</dd></div>
                </dl>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function IntegratedPage() {
  const { authStatus, expiresAt, logout, calendars, resourcesLoading, loadResources, notice,
    grants, states, selectedDomain, refreshEvents } = useLocalIntegration();
  useEffect(() => {
    if (authStatus === "authenticated") void loadResources();
  }, [authStatus, loadResources]);
  useEffect(() => {
    if (authStatus === "authenticated" && hasDomainGrant(grants, selectedDomain) && states.some((state) => state.domain_id === selectedDomain)) {
      void refreshEvents();
    }
  }, [authStatus, grants, selectedDomain, states, refreshEvents]);

  return (
    <div className="mx-auto max-w-[920px] px-4 py-6 pb-8 md:px-8 md:py-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">ÁREA TÉCNICA</div>
          <h1 className="prose-editorial mt-1 text-[28px] font-medium leading-tight tracking-tight text-ink md:text-[34px]">Integração local</h1>
          <p data-testid="google-not-connected" className="mt-2 max-w-[650px] text-sm leading-relaxed text-ink-subtle">
            Teste permissões e leitura de uma agenda de exemplo neste aparelho. Nenhuma conta externa está conectada.
          </p>
        </div>
        <Badge tone="violet">Demonstração local</Badge>
      </div>

      <details className="mt-3 rounded-xl border border-paper-border bg-white px-4 py-3 text-xs text-ink-subtle">
        <summary className="min-h-11 cursor-pointer py-3 font-medium text-ink">Sobre esta área técnica</summary>
        <p>O serviço local usa SQLite e uma agenda fictícia, separada das demais informações de exemplo. Ele não importa dados da demonstração e não acessa contas reais.</p>
      </details>

      {authStatus === "checking" ? (
        <div className="mt-5 rounded-2xl border border-paper-border bg-white p-5 text-sm text-ink-subtle" role="status">Verificando sessão local…</div>
      ) : authStatus === "anonymous" ? (
        <LoginForm />
      ) : (
        <>
          <Card className="mt-5 flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div className="text-sm text-ink-subtle">
              Sessão ativa neste aparelho até <span className="font-medium text-ink">{localDate(expiresAt)}</span>.
              <details className="mt-1 text-xs"><summary className="min-h-11 cursor-pointer py-3">Detalhes técnicos da sessão</summary><p>A sessão usa cookie HttpOnly. Sessões e permissões em memória expiram ao reiniciar o serviço.</p></details>
            </div>
            <Button size="sm" variant="outline" onClick={() => void logout()}>Encerrar sessão</Button>
          </Card>
          {notice && <p role="alert" className="mt-3 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-900">{notice}</p>}
          <div className="mt-5 grid gap-4">
            <GrantControls />
            <section aria-labelledby="calendars-title" className="space-y-3">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <h2 id="calendars-title" className="text-base font-semibold text-ink">Catálogo fictício e classificação</h2>
                  <p className="mt-1 text-sm text-ink-subtle">Sem classificação ou concessão compatível, o calendário permanece em quarentena.</p>
                </div>
                <Button size="sm" variant="ghost" disabled={resourcesLoading} onClick={() => void loadResources()}>
                  {resourcesLoading ? "Atualizando…" : "Atualizar estados"}
                </Button>
              </div>
              {resourcesLoading && calendars.length === 0 ? <p role="status" className="text-sm text-ink-subtle">Carregando somente dados autorizados…</p> : null}
              <div className="grid gap-3 md:grid-cols-2">
                {calendars.map((calendar) => <CalendarCard key={calendar.calendar_id} calendar={calendar} />)}
              </div>
            </section>
          </div>
          <IntegratedNow />
        </>
      )}

      <div className="mt-8 flex flex-wrap gap-2 border-t border-paper-border pt-4">
        <Link href="/" className="inline-flex min-h-11 items-center rounded-full border border-paper-border bg-white px-4 py-2 text-sm font-medium text-ink hover:bg-paper-muted">Voltar ao Agora</Link>
        <details className="self-center text-xs text-ink-subtle"><summary className="min-h-11 cursor-pointer py-3">Limites técnicos</summary><p>Um processo local, sem conexão de rede externa, escrita em contas ou dados reais.</p></details>
      </div>
    </div>
  );
}

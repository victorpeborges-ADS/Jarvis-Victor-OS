"use client";

import { useEffect, useMemo, useState } from "react";
import { Dialog } from "@/components/ui/Dialog";
import { Badge, Card } from "@/components/ui/primitives";
import type { Mission } from "@/lib/mission-contracts";
import { cancelMission, createMission, failMissionTask, retryMissionTask } from "@/lib/mission-core";
import { clearMissionQuarantine, getMissionQuarantine, loadMissions, loadMissionsWithRecovery, MISSION_STORAGE_KEY, runAndSaveNextStep, saveMissions, type QuarantinedMissionRecord } from "@/lib/mission-store";

const DOMAINS = [
  { id: "dom_synthetic_a", label: "Escopo sintético A" },
  { id: "dom_synthetic_b", label: "Escopo sintético B" }
];

const statusLabels: Record<Mission["status"], string> = {
  draft: "Rascunho", planned: "Planejada", awaiting_approval: "Aguardando aprovação", running: "Em simulação",
  blocked: "Bloqueada", done: "Concluída", cancelled: "Cancelada", failed: "Falhou"
};

export default function MissionsPage() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [domainId, setDomainId] = useState(DOMAINS[0].id);
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("Carregando missões locais sintéticas.");
  const [reviewArtifactId, setReviewArtifactId] = useState<string | null>(null);
  const [quarantineCount, setQuarantineCount] = useState(0);
  const [quarantineTruncated, setQuarantineTruncated] = useState(false);
  const [recoveryError, setRecoveryError] = useState(false);
  const [pendingQuarantine, setPendingQuarantine] = useState<QuarantinedMissionRecord[]>([]);
  const selected = useMemo(() => missions.find((mission) => mission.id === selectedId) ?? null, [missions, selectedId]);
  const reviewArtifact = selected?.artifacts.find((artifact) => artifact.id === reviewArtifactId) ?? null;

  useEffect(() => {
    const result = loadMissionsWithRecovery(window.localStorage);
    setMissions(result.missions);
    setSelectedId(result.missions[0]?.id ?? null);
    setQuarantineCount(result.quarantinedCount);
    setQuarantineTruncated(result.quarantineTruncated);
    setRecoveryError(result.recoveryError);
    setPendingQuarantine(result.pendingQuarantine);
    setReady(true);
    setMessage(result.quarantinedCount
      ? `${result.missions.length} missão(ões) válida(s) recuperada(s); ${result.quarantinedCount} registro(s) inválido(s) isolado(s).`
      : result.missions.length ? "Missões sintéticas locais recuperadas deste navegador." : "Nenhuma missão local. Crie uma simulação para começar.");
  }, []);

  function persist(next: Mission[], notice: string) {
    if (recoveryError) {
      setMessage("Os registros inválidos continuam preservados. Baixe a cópia, libere espaço local e recarregue antes de editar.");
      return;
    }
    saveMissions(window.localStorage, next);
    setMissions(next);
    setMessage(notice);
  }

  function downloadQuarantine() {
    const quarantine = getMissionQuarantine(window.localStorage);
    const blob = new Blob([JSON.stringify({ ...quarantine, records: [...quarantine.records, ...pendingQuarantine] }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "jarvis-missoes-quarentena-recuperacao.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  function discardQuarantine() {
    clearMissionQuarantine(window.localStorage);
    setQuarantineCount(0);
    setQuarantineTruncated(false);
    setRecoveryError(false);
    setPendingQuarantine([]);
    setMessage("Cópia isolada descartada. As missões válidas foram mantidas.");
  }

  function onCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!title.trim()) return;
    const mission = createMission(title, domainId);
    persist([mission, ...missions], "Missão criada com etapas sintéticas e orçamento zero.");
    setSelectedId(mission.id);
    setTitle("");
  }

  function onRun() {
    if (!selected) return;
    const requestKey = `${selected.id}:ui:${selected.tasks.find((task) => task.status === "planned" || task.status === "blocked")?.id ?? "complete"}:${Date.now()}`;
    const next = runAndSaveNextStep(window.localStorage, selected.id, requestKey, new Date().toISOString());
    if (!next) return;
    const latest = loadMissions(window.localStorage);
    setMissions(latest);
    setMessage(next.status === "done" ? "Simulação concluída. Rascunho local disponível para revisão humana." : "Uma etapa determinística foi concluída localmente.");
  }

  function onCancel() {
    if (!selected) return;
    const updated = cancelMission(selected);
    persist(missions.map((mission) => mission.id === selected.id ? updated : mission), "Missão cancelada localmente.");
  }

  function onRetry() {
    if (!selected) return;
    const failed = selected.tasks.find((task) => task.status === "failed");
    if (!failed) return;
    const updated = retryMissionTask(selected, failed.id);
    persist(missions.map((mission) => mission.id === selected.id ? updated : mission), "Nova tentativa local preparada com chave idempotente.");
  }

  function onSimulateFailure() {
    if (!selected) return;
    const pending = selected.tasks.find((task) => task.status === "planned");
    if (!pending) return;
    const updated = failMissionTask(selected, pending.id, "Falha sintética solicitada para demonstrar retry seguro.");
    persist(missions.map((mission) => mission.id === selected.id ? updated : mission), "Falha de demonstração registrada; nenhum serviço foi chamado.");
  }

  function decideReview(review_state: "approved_locally" | "rejected") {
    if (!selected || !reviewArtifactId) return;
    const now = new Date().toISOString();
    const updated = { ...selected, artifacts: selected.artifacts.map((artifact) => artifact.id === reviewArtifactId ? { ...artifact, review_state, reviewed_at: now } : artifact), updated_at: now };
    persist(missions.map((mission) => mission.id === selected.id ? updated : mission), review_state === "approved_locally" ? "Rascunho aprovado para uso local. Nada foi publicado." : "Rascunho rejeitado localmente.");
    setReviewArtifactId(null);
  }

  const canRun = Boolean(ready && !recoveryError && selected && !["done", "cancelled", "failed"].includes(selected.status));

  return (
    <div className="mx-auto max-w-[960px] px-4 py-6 md:px-8 md:py-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">CENTRAL LOCAL</div>
          <h1 className="prose-editorial mt-1 text-[30px] font-medium leading-tight tracking-tight text-ink md:text-[36px]">Missões</h1>
          <p className="mt-2 max-w-[620px] text-sm leading-relaxed text-ink-subtle">Planeje etapas, acompanhe checkpoints e revise rascunhos gerados por regras locais.</p>
        </div>
        <Badge tone="amber">SIMULAÇÃO · 100% SINTÉTICA</Badge>
      </div>

      <div role="status" aria-live="polite" className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950" data-testid="mission-simulation-banner">
        Armazenamento deste navegador · API desconectada · teto de custo 0 · nenhuma escrita externa.
      </div>

      {quarantineCount > 0 && <section role="alert" className="mt-4 rounded-xl border border-orange-300 bg-orange-50 p-4 text-sm text-orange-950" data-testid="mission-quarantine-notice">
        <p><strong>{quarantineCount} registro(s) local(is) inválido(s) {recoveryError ? "foram detectados; a origem foi preservada" : "foram isolados"}.</strong> Missões válidas foram recuperadas e continuam disponíveis.</p>
        <p className="mt-1">Baixe a cópia para revisão e recuperação manual.{quarantineTruncated ? " Alguns registros foram limitados pelo teto local de armazenamento." : ""}{recoveryError ? " O navegador não conseguiu salvar a quarentena separada; edição local fica pausada até recuperar espaço e recarregar." : ""}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={downloadQuarantine} className="rounded-lg border border-orange-400 bg-white px-3 py-2 font-medium">Baixar pacote de recuperação</button>
          {!recoveryError && <button type="button" onClick={discardQuarantine} className="rounded-lg border border-orange-400 bg-white px-3 py-2 font-medium">Descartar cópia isolada</button>}
        </div>
      </section>}

      <div className="mt-5 grid gap-5 md:grid-cols-[300px_1fr]">
        <section aria-labelledby="missions-list-heading">
          <Card className="p-4">
            <h2 id="missions-list-heading" className="text-sm font-semibold text-ink">Criar missão sintética</h2>
            <form onSubmit={onCreate} className="mt-3 space-y-3">
              <label className="block text-xs font-medium text-ink-subtle" htmlFor="mission-title">Nome</label>
              <input id="mission-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={240} required placeholder="Ex.: Revisar fontes fictícias" className="w-full rounded-xl border border-paper-border bg-white px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-violet-500" />
              <label className="block text-xs font-medium text-ink-subtle" htmlFor="mission-domain">Escopo</label>
              <select id="mission-domain" value={domainId} onChange={(event) => setDomainId(event.target.value)} className="w-full rounded-xl border border-paper-border bg-white px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-violet-500">
                {DOMAINS.map((domain) => <option key={domain.id} value={domain.id}>{domain.label}</option>)}
              </select>
              <button type="submit" disabled={!ready || recoveryError || !title.trim()} className="w-full rounded-full bg-ink px-4 py-2.5 text-sm font-medium text-white hover:bg-action-hover focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-50">Criar missão</button>
            </form>
          </Card>
          <div className="mt-4" aria-label="Lista de missões">
            <h2 className="mb-2 px-1 text-xs font-semibold tracking-widest text-ink-faint">MISSÕES LOCAIS · {missions.length}</h2>
            <div className="space-y-2">
              {missions.map((mission) => (
                <button key={mission.id} type="button" onClick={() => setSelectedId(mission.id)} aria-pressed={selectedId === mission.id} className={`w-full rounded-xl border px-3 py-3 text-left focus:outline-none focus:ring-2 focus:ring-violet-500 ${selectedId === mission.id ? "border-ink bg-paper-muted" : "border-paper-border bg-white hover:bg-paper-muted/60"}`}>
                  <span className="block truncate text-sm font-medium text-ink">{mission.title}</span>
                  <span className="mt-1 block text-xs text-ink-faint">{statusLabels[mission.status]} · {mission.tasks.filter((task) => task.status === "done").length}/{mission.tasks.length} etapas</span>
                </button>
              ))}
              {!missions.length && <p className="rounded-xl border border-dashed border-paper-border px-3 py-4 text-sm text-ink-faint">Missões criadas aqui permanecem no armazenamento local deste navegador.</p>}
            </div>
          </div>
        </section>

        <section aria-labelledby="mission-detail-heading" aria-busy={!ready}>
          {selected ? (
            <>
              <Card className="p-5 md:p-6">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="text-xs font-semibold tracking-widest text-ink-faint">MISSÃO SINTÉTICA · {statusLabels[selected.status].toUpperCase()}</div>
                    <h2 id="mission-detail-heading" className="prose-editorial mt-2 text-2xl font-medium leading-tight text-ink">{selected.title}</h2>
                    <p className="mt-2 text-sm text-ink-subtle">{selected.description}</p>
                  </div>
                  <Badge tone="violet">CUSTO {selected.budget.spent}/{selected.budget.cap}</Badge>
                </div>
                <div className="mt-5 flex flex-wrap gap-2">
                  <button type="button" disabled={!canRun} onClick={onRun} className="rounded-full bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-action-hover focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-40">Executar próxima etapa · simulada</button>
                  <button type="button" disabled={!canRun} onClick={onCancel} className="rounded-full border border-paper-border bg-white px-4 py-2 text-sm font-medium text-ink hover:bg-paper-muted focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-40">Cancelar</button>
                  {selected.status === "failed" && <button type="button" disabled={recoveryError} onClick={onRetry} className="rounded-full border border-violet-300 bg-violet-50 px-4 py-2 text-sm font-medium text-violet-950 focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-40">Preparar retry local</button>}
                  {selected.status !== "failed" && selected.status !== "done" && selected.status !== "cancelled" && <button type="button" disabled={recoveryError} onClick={onSimulateFailure} className="rounded-full border border-paper-border bg-white px-3 py-2 text-xs text-ink-subtle hover:bg-paper-muted focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-40">Demonstrar falha/retry</button>}
                </div>
                <p className="mt-3 text-xs text-ink-faint" role="status" aria-live="polite">{message}</p>
              </Card>

              <Card className="mt-4 p-5">
                <h3 className="text-sm font-semibold text-ink">Etapas e dependências</h3>
                <ol className="mt-3 space-y-2">
                  {selected.tasks.map((task, index) => (
                    <li key={task.id} data-testid="mission-task" className="flex gap-3 rounded-xl border border-paper-border bg-white px-3 py-3">
                      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-paper-muted text-xs text-ink-subtle">{index + 1}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center justify-between gap-1">
                          <span className="text-sm font-medium text-ink">{task.title}</span>
                          <span className="text-xs text-ink-faint">{statusLabels[task.status]} · tentativa {task.attempt}</span>
                        </div>
                        {task.depends_on.length > 0 && <p className="mt-1 text-xs text-ink-faint">Depende de {task.depends_on.map((dependency) => selected.tasks.find((entry) => entry.id === dependency)?.title).join(", ")}</p>}
                        {task.failure_reason && <p className="mt-1 text-xs text-red-700">{task.failure_reason}</p>}
                      </div>
                    </li>
                  ))}
                </ol>
              </Card>

              {selected.artifacts.length > 0 && <Card className="mt-4 p-5">
                <h3 className="text-sm font-semibold text-ink">Rascunhos e evidências · revisão humana</h3>
                <div className="mt-3 space-y-3">
                  {selected.artifacts.map((artifact) => <article key={artifact.id} className="rounded-xl border border-paper-border bg-paper-muted/50 p-3" data-testid="mission-artifact">
                    <h4 className="text-sm font-medium text-ink">{artifact.title}</h4>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-ink-subtle">{artifact.content}</p>
                    <p className="mt-2 text-xs text-ink-faint">Origem: {artifact.source_refs.map((source) => source.source_id).join(", ") || "sem fonte"} · skill {artifact.skill_version ?? "não informada"}</p>
                    {artifact.kind === "report" && <div className="mt-3 flex flex-wrap items-center gap-2">
                      <span className="text-xs text-ink-subtle">Revisão: {artifact.review_state === "approved_locally" ? "aprovado localmente" : artifact.review_state === "rejected" ? "rejeitado" : "aguardando Victor"}</span>
                      <button type="button" onClick={() => setReviewArtifactId(artifact.id)} className="rounded-full border border-paper-border bg-white px-3 py-1.5 text-xs font-medium text-ink underline underline-offset-2 focus:outline-none focus:ring-2 focus:ring-violet-500" aria-label={`Revisar fontes e decisão — ${artifact.title}`}>Fontes e aprovação</button>
                    </div>}
                  </article>)}
                </div>
              </Card>}

              <Card className="mt-4 p-5">
                <h3 className="text-sm font-semibold text-ink">Histórico e checkpoints</h3>
                <ol className="mt-3 space-y-2">
                  {selected.events.slice().reverse().map((item) => <li key={item.id} className="border-l-2 border-violet-200 pl-3 text-sm text-ink-subtle"><span className="block">{item.message}</span><time className="mt-0.5 block text-xs text-ink-faint" dateTime={item.created_at}>{new Date(item.created_at).toLocaleString("pt-BR")}</time></li>)}
                </ol>
                <p className="mt-3 text-xs text-ink-faint">{selected.checkpoints.length} checkpoints · chave de armazenamento {MISSION_STORAGE_KEY}</p>
              </Card>
            </>
          ) : <Card className="p-8 text-center text-sm text-ink-subtle"><h2 id="mission-detail-heading" className="font-semibold text-ink">Crie ou selecione uma missão</h2><p className="mt-2">A simulação não lê a API local nem os dados DEMO do Gate 1.</p></Card>}
        </section>
      </div>
      <Dialog open={Boolean(reviewArtifact)} onClose={() => setReviewArtifactId(null)} titleId="mission-review-title" label={reviewArtifact?.title ?? "Fontes e aprovação local"}>
        <div className="flex items-start justify-between gap-3 border-b border-paper-border p-5">
          <div><div className="text-xs font-semibold tracking-widest text-ink-faint">REVISÃO LOCAL · SINTÉTICA</div><h2 id="mission-review-title" className="mt-1 text-lg font-semibold text-ink">Fontes e aprovação</h2></div>
          <button type="button" onClick={() => setReviewArtifactId(null)} aria-label="Fechar revisão" className="rounded-full bg-paper-muted px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500">Fechar</button>
        </div>
        {reviewArtifact && <div className="flex-1 overflow-auto p-5">
          <h3 className="text-sm font-semibold text-ink">{reviewArtifact.title}</h3>
          <p className="mt-2 text-sm text-ink-subtle">A decisão vale somente para este rascunho guardado no navegador. Ela não envia, publica nem autoriza uma fonte externa.</p>
          <div className="mt-4 space-y-2">
            {reviewArtifact.source_refs.length ? reviewArtifact.source_refs.map((source) => <div key={source.source_id} className="rounded-xl border border-paper-border bg-paper-muted/50 p-3 text-xs text-ink-subtle">
              <div className="font-medium text-ink">{source.source_id}</div>
              <div className="mt-1">Escopo: {source.domain_id ?? "não classificado"} · Observado: {source.observed_at}</div>
              <div>Última verificação: {source.last_verified_at ?? "não verificado"} · Validade: {source.valid_until ?? "sem prazo indicado"}</div>
            </div>) : <p className="rounded-xl border border-dashed border-paper-border p-3 text-sm text-ink-faint">Este rascunho não declara uma fonte.</p>}
          </div>
          <p className="mt-4 text-xs text-ink-faint">Estado da decisão: {reviewArtifact.review_state ?? "não requerido"}</p>
          {reviewArtifact.review_state === "awaiting_approval" && <div className="mt-5 flex flex-wrap gap-2">
            <button type="button" disabled={recoveryError} onClick={() => decideReview("approved_locally")} className="rounded-full bg-ink px-4 py-2 text-sm font-medium text-white focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-40">Aprovar para uso local</button>
            <button type="button" disabled={recoveryError} onClick={() => decideReview("rejected")} className="rounded-full border border-paper-border px-4 py-2 text-sm font-medium text-ink focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-40">Rejeitar rascunho</button>
          </div>}
        </div>}
      </Dialog>
      <p className="mt-5 text-center text-xs leading-relaxed text-ink-faint">Estado salvo somente em localStorage neste navegador. Limpar o perfil do navegador remove a simulação.</p>
    </div>
  );
}

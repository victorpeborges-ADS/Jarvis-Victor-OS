"use client";

import { useRef, useState } from "react";
import { Dialog } from "@/components/ui/Dialog";
import { Badge, Button, Card } from "@/components/ui/primitives";
import { LocalApiError, localApiRequest, type LocalSession } from "@/lib/local-api";
import type { Artifact, Mission, MissionRecord } from "@/lib/mission-contracts";
import { planMissionImport } from "@/lib/mission-import";
import { loadMissions, MISSION_STORAGE_KEY } from "@/lib/mission-store";

type Listed = { dataset: "api_synthetic"; items: Array<MissionRecord & { available_actions?: string[] }>; next_cursor: string | null };

export interface ReviewItem {
  id: string;
  mission_id: string;
  mission_title: string;
  mission_status: string;
  artifact_id: string;
  artifact_version: number;
  artifact_sha256: string;
  artifact_title: string;
  artifact_kind: string;
  domain_id: string;
  state: "pending" | "approved" | "rejected" | "changes_requested";
  decision_reason: string | null;
  decision_actor: string | null;
  decided_at: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  artifact?: Artifact;
  history?: Array<{
    id: string;
    decision: string;
    decision_reason: string | null;
    actor: string;
    idempotency_key: string;
    created_at: string;
  }>;
}

function messageFor(error: unknown): string {
  if (error instanceof LocalApiError) {
    if (error.status === 401) return "Sessão ausente (401). Entre na integração local antes de usar a API.";
    if (error.status === 403) return "Concessão ausente (403). Exige concessão específica no domínio.";
    if (error.status === 409) return "Conflito (409): a versão ou o estado já foi alterado no servidor. Recarregue.";
    if (error.status === 422) return `Requisição rejeitada (422): ${error.message}`;
    return error.message;
  }
  return "A API local sintética não respondeu.";
}

export function MissionApiPanel() {
  const [open, setOpen] = useState(false);
  const [records, setRecords] = useState<Array<MissionRecord & { available_actions?: string[] }>>([]);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [notice, setNotice] = useState("API local sintética desligada nesta tela. O modo DEMO continua no navegador.");
  const [busy, setBusy] = useState(false);
  const [previewCount, setPreviewCount] = useState(0);
  const [quarantineCount, setQuarantineCount] = useState(0);
  const [clearLocal, setClearLocal] = useState(false);
  const [pending, setPending] = useState<Mission[]>([]);

  // Review inspection and decision state
  const [selectedReview, setSelectedReview] = useState<ReviewItem | null>(null);
  const [decisionType, setDecisionType] = useState<"approved" | "rejected" | "changes_requested" | null>(null);
  const [decisionReason, setDecisionReason] = useState("");
  const [reviseContent, setReviseContent] = useState("");
  const [modalNotice, setModalNotice] = useState<string | null>(null);
  const decisionAttempts = useRef(new Map<string, string>());

  async function load() {
    setBusy(true);
    try {
      const { data } = await localApiRequest<Listed>("/real/missions?limit=20");
      if (!data || data.dataset !== "api_synthetic") {
        setNotice("A resposta não é da API local sintética. Nada foi copiado do DEMO.");
        setRecords([]);
        return;
      }
      setRecords(data.items);
      setNotice(`${data.items.length} missão(ões) na API local sintética.`);
      await loadReviews();
    } catch (error) {
      setRecords([]);
      setNotice(messageFor(error));
    } finally {
      setBusy(false);
    }
  }

  async function loadReviews() {
    try {
      const { data } = await localApiRequest<{ dataset: string; items: ReviewItem[] }>("/real/reviews?limit=20");
      if (data?.items) {
        setReviews(data.items);
      }
    } catch (error) {
      setReviews([]);
      setNotice(`Não foi possível carregar a fila de revisão: ${messageFor(error)}`);
    }
  }

  function preview() {
    const planned = planMissionImport(loadMissions(window.localStorage));
    setPending(planned.accepted);
    setPreviewCount(planned.accepted.length);
    setQuarantineCount(planned.quarantined.length);
    setNotice(`${planned.accepted.length} válida(s) para envio; ${planned.quarantined.length} em quarentena local. A fonte do navegador ainda não foi apagada.`);
  }

  async function confirmImport() {
    if (pending.length === 0) return;
    setBusy(true);
    try {
      const session = await localApiRequest<LocalSession>("/real/session");
      if (!session.data?.csrf_token) {
        setNotice("Sessão ausente (401). Entre na integração local antes de importar.");
        return;
      }
      const { data } = await localApiRequest<{ accepted: string[]; quarantined: unknown[]; dataset: string }>("/real/missions/import", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": session.data.csrf_token },
        body: JSON.stringify({ missions: pending, idempotency_key: `import-${pending.map((item) => item.id).join("-")}`.slice(0, 160), confirm: true })
      });
      if (!data || data.dataset !== "api_synthetic") {
        setNotice("O servidor não confirmou o dataset sintético. O navegador foi preservado.");
        return;
      }
      if (clearLocal && data.accepted.length === pending.length) {
        window.localStorage.setItem(MISSION_STORAGE_KEY, "[]");
        setNotice("Importação confirmada e a fonte local foi esvaziada por escolha explícita.");
      } else {
        setNotice("Importação confirmada. A cópia do navegador foi mantida.");
      }
      setPending([]);
      await load();
    } catch (error) {
      setNotice(messageFor(error));
    } finally {
      setBusy(false);
    }
  }

  async function act(record: MissionRecord & { available_actions?: string[]; revision: number }, action: string) {
    setBusy(true);
    try {
      const session = await localApiRequest<LocalSession>("/real/session");
      if (!session.data?.csrf_token) {
        setNotice("Sessão ausente (401). A API não executou a etapa.");
        return;
      }
      await localApiRequest(`/real/missions/${encodeURIComponent(record.mission.id)}/transition`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": session.data.csrf_token },
        body: JSON.stringify({
          action,
          expected_revision: record.revision,
          idempotency_key: `${action}-${record.mission.id}-${record.revision}`.slice(0, 160)
        })
      });
      setNotice(`Ação ${action} confirmada pelo servidor. O DEMO local não foi alterado.`);
      await load();
    } catch (error) {
      setNotice(messageFor(error));
    } finally {
      setBusy(false);
    }
  }

  async function openReviewDetail(reviewId: string) {
    setBusy(true);
    setModalNotice(null);
    setDecisionType(null);
    setDecisionReason("");
    setReviseContent("");
    try {
      const { data } = await localApiRequest<ReviewItem>(`/real/reviews/${encodeURIComponent(reviewId)}`);
      if (data) {
        setSelectedReview(data);
      }
    } catch (error) {
      setNotice(messageFor(error));
    } finally {
      setBusy(false);
    }
  }

  async function submitDecision(decision: "approved" | "rejected" | "changes_requested") {
    if (!selectedReview) return;
    if ((decision === "rejected" || decision === "changes_requested") && !decisionReason.trim()) {
      setModalNotice("Justificativa obrigatória para rejeição ou solicitação de ajustes.");
      return;
    }
    setBusy(true);
    setModalNotice(null);
    try {
      const session = await localApiRequest<LocalSession>("/real/session");
      if (!session.data?.csrf_token) {
        setModalNotice("Sessão ausente (401). Entre na integração local.");
        return;
      }
      const attempt = JSON.stringify([selectedReview.id, selectedReview.revision,
        selectedReview.artifact_sha256, decision, decisionReason.trim()]);
      let idempotencyKey = decisionAttempts.current.get(attempt);
      if (!idempotencyKey) {
        idempotencyKey = `decide-${crypto.randomUUID()}`;
        decisionAttempts.current.set(attempt, idempotencyKey);
      }
      const { data } = await localApiRequest<ReviewItem>(`/real/reviews/${encodeURIComponent(selectedReview.id)}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": session.data.csrf_token },
        body: JSON.stringify({
          decision,
          expected_revision: selectedReview.revision,
          expected_artifact_sha256: selectedReview.artifact_sha256,
          reason: decisionReason.trim() || null,
          idempotency_key: idempotencyKey
        })
      });
      if (data) {
        setSelectedReview(data);
        setDecisionType(null);
        setDecisionReason("");
        setModalNotice(`Decisão ${decision} confirmada pelo servidor (revisão ${data.revision}).`);
        await loadReviews();
        await load();
      }
    } catch (error) {
      try {
        const { data } = await localApiRequest<ReviewItem>(`/real/reviews/${encodeURIComponent(selectedReview.id)}`);
        if (data && (data.revision !== selectedReview.revision || data.state !== selectedReview.state)) {
          setSelectedReview(data);
          setDecisionType(null);
          setModalNotice(`O servidor registrou o estado “${data.state}”. A revisão foi atualizada após a resposta interrompida.`);
          await loadReviews();
        } else {
          setModalNotice(`${messageFor(error)} O estado continua pendente; você pode repetir a decisão com a mesma chave.`);
        }
      } catch {
        setModalNotice(`${messageFor(error)} Não foi possível confirmar o resultado. Tente novamente; a mesma chave será reutilizada.`);
      }
    } finally {
      setBusy(false);
    }
  }

  async function submitRevision() {
    if (!selectedReview || !reviseContent.trim()) {
      setModalNotice("Conteúdo revisado obrigatório.");
      return;
    }
    setBusy(true);
    setModalNotice(null);
    try {
      const session = await localApiRequest<LocalSession>("/real/session");
      if (!session.data?.csrf_token) {
        setModalNotice("Sessão ausente (401).");
        return;
      }
      const idempotencyKey = `revise-${selectedReview.id}-${Date.now()}`;
      const { data } = await localApiRequest<ReviewItem>(`/real/reviews/${encodeURIComponent(selectedReview.id)}/revise`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": session.data.csrf_token },
        body: JSON.stringify({
          new_content: reviseContent.trim(),
          idempotency_key: idempotencyKey
        })
      });
      if (data) {
        setSelectedReview(data);
        setReviseContent("");
        setModalNotice(`Versão ${data.artifact_version} enviada para nova revisão.`);
        await loadReviews();
        await load();
      }
    } catch (error) {
      setModalNotice(messageFor(error));
    } finally {
      setBusy(false);
    }
  }

  async function grantReviewPermission(domainId = "dom_synthetic_a") {
    setBusy(true);
    try {
      const session = await localApiRequest<LocalSession>("/real/session");
      if (!session.data?.csrf_token) {
        setNotice("Sessão ausente (401). Entre antes de conceder permissão.");
        return;
      }
      await localApiRequest("/real/grants", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": session.data.csrf_token },
        body: JSON.stringify({
          connector: "mission_sim",
          permission: "read",
          resource_ids: ["mission:review"],
          domain_ids: [domainId],
          expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString()
        })
      });
      setNotice(`Concessão mission:review ativa para ${domainId}.`);
    } catch (error) {
      setNotice(messageFor(error));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="mt-6">
        <Button type="button" variant="outline" data-testid="mission-api-open" onClick={() => setOpen(true)}>
          Abrir API local sintética
        </Button>
      </div>
    );
  }

  return (
    <Card className="mt-6 p-5" data-testid="mission-api-panel">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-ink">API local sintética</h2>
          <p className="mt-1 text-sm text-ink-subtle">Fonte de verdade separada do DEMO. Sem fallback silencioso e sem apagar o navegador antes da confirmação.</p>
        </div>
        <Badge tone="violet">API LOCAL · SINTÉTICA</Badge>
      </div>
      <p className="mt-3 text-sm text-ink" role="status">{notice}</p>

      {/* Seção de Missões */}
      <div className="mt-4 border-t border-paper-border pt-4">
        <h3 className="text-sm font-semibold text-ink">Missões na API</h3>
        <ul className="mt-2 space-y-3">
          {records.map((record) => (
            <li key={record.mission.id} className="rounded-xl border border-paper-border px-3 py-2 text-sm" data-testid="mission-api-card">
              <div className="font-medium">{record.mission.title}</div>
              <div className="text-ink-faint">API local sintética · {record.mission.status} · revisão {record.revision}</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {(record.available_actions ?? []).map((action) => (
                  <Button key={action} type="button" variant="outline" disabled={busy} onClick={() => void act(record, action)}>
                    {action}
                  </Button>
                ))}
              </div>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" disabled={busy} onClick={() => void load()}>Ler missões da API</Button>
          <Button type="button" variant="outline" disabled={busy} onClick={preview}>Prévia da importação</Button>
          <Button type="button" variant="outline" disabled={busy || pending.length === 0} onClick={() => void confirmImport()}>Confirmar envio</Button>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" checked={clearLocal} onChange={(event) => setClearLocal(event.target.checked)} />
          Apagar a fonte local só depois que o servidor confirmar todos os itens válidos
        </label>
        <p className="mt-2 text-xs text-ink-faint">Prévia: {previewCount} aceita(s), {quarantineCount} em quarentena.</p>
      </div>

      {/* Seção de Fila de Revisão Humana */}
      <div className="mt-6 border-t border-paper-border pt-4" data-testid="review-queue-section">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-ink">Fila de Revisão de Artefatos</h3>
            <p className="text-xs text-ink-subtle">Decisões humanas duráveis e explícitas (G5). Exige concessão mission:review.</p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void grantReviewPermission("dom_synthetic_a")}>
              Conceder mission:review (Escopo A)
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void loadReviews()}>
              Atualizar fila de revisão
            </Button>
          </div>
        </div>

        {reviews.length === 0 ? (
          <p className="mt-3 text-sm text-ink-subtle" data-testid="review-empty-notice">
            Nenhum artefato pendente na fila de revisão. Execute etapas da missão para produzir rascunhos.
          </p>
        ) : (
          <ul className="mt-3 space-y-3" data-testid="review-queue">
            {reviews.map((rev) => (
              <li key={rev.id} className="rounded-xl border border-paper-border bg-paper-muted/40 p-3 text-sm" data-testid="review-card">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold text-ink">{rev.artifact_title} (v{rev.artifact_version})</div>
                    <div className="text-xs text-ink-subtle">
                      Missão: {rev.mission_title} ({rev.mission_status}) · ID: {rev.artifact_id}
                    </div>
                    {rev.decision_reason && (
                      <div className="mt-1 text-xs text-ink-faint">Motivo: {rev.decision_reason}</div>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={rev.state === "approved" ? "emerald" : rev.state === "rejected" ? "red" : rev.state === "changes_requested" ? "amber" : "neutral"}>
                      {rev.state === "pending" ? "Aguardando revisão" : rev.state === "approved" ? "Aprovado" : rev.state === "rejected" ? "Rejeitado" : "Ajustes solicitados"}
                    </Badge>
                    <Button size="sm" variant="outline" data-testid="review-open-button" onClick={() => void openReviewDetail(rev.id)}>
                      Examinar e Decidir
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Modal de Detalhe e Decisão de Revisão */}
      <Dialog
        open={Boolean(selectedReview)}
        onClose={() => setSelectedReview(null)}
        titleId="review-dialog-title"
        label="Revisão de Artefato Sintético"
      >
        {selectedReview && (
          <div className="space-y-4" data-testid="review-detail">
            <div>
              <div className="text-xs font-semibold tracking-widest text-ink-faint">REVISÃO HUMANA · API LOCAL SINTÉTICA</div>
              <h2 id="review-dialog-title" className="mt-1 text-lg font-semibold text-ink">
                {selectedReview.artifact_title} (Versão {selectedReview.artifact_version})
              </h2>
              <p className="text-xs text-ink-subtle">
                Missão: {selectedReview.mission_title} ({selectedReview.mission_status}) · Domínio: {selectedReview.domain_id}
              </p>
            </div>

            {/* Conteúdo Exato */}
            <div className="rounded-xl border border-paper-border bg-paper-muted p-3">
              <div className="text-xs font-semibold text-ink-subtle">CONTEÚDO DO RASCUNHO (SNAPSHOT IMUTÁVEL)</div>
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded border border-paper-border bg-white p-2.5 text-xs font-mono text-ink" data-testid="review-artifact-content">
                {selectedReview.artifact?.content ?? "Carregando conteúdo..."}
              </pre>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-ink-faint">
                <span>Digest: <span className="font-mono">{selectedReview.artifact_sha256.slice(0, 16)}...</span></span>
                <span>Tipo: {selectedReview.artifact_kind}</span>
                <span>Skill: {selectedReview.artifact?.skill_id ?? "sintética"} (v{selectedReview.artifact?.skill_version ?? "1.0.0"})</span>
              </div>
            </div>

            {modalNotice && (
              <p role="alert" className="rounded-xl bg-violet-50 p-2.5 text-xs text-violet-950 font-medium" data-testid="review-modal-notice">
                {modalNotice}
              </p>
            )}

            {/* Ações quando Pending */}
            {selectedReview.state === "pending" && !decisionType && (
              <div className="flex flex-wrap gap-2 pt-2 border-t border-paper-border">
                <Button data-testid="review-approve-button" disabled={busy} onClick={() => setDecisionType("approved")}>
                  Aprovar rascunho
                </Button>
                <Button variant="outline" data-testid="review-changes-button" disabled={busy} onClick={() => setDecisionType("changes_requested")}>
                  Solicitar ajustes
                </Button>
                <Button variant="outline" data-testid="review-reject-button" disabled={busy} onClick={() => setDecisionType("rejected")}>
                  Rejeitar rascunho
                </Button>
              </div>
            )}

            {/* Confirmação com Justificativa */}
            {decisionType && (
              <div className="rounded-xl border border-paper-border bg-white p-3 space-y-3" data-testid="review-decision-form">
                <div className="text-sm font-semibold text-ink">
                  {decisionType === "approved" ? "Confirmar Aprovação" : decisionType === "rejected" ? "Confirmar Rejeição" : "Solicitar Ajustes"}
                </div>
                {decisionType !== "approved" && (
                  <div>
                    <label className="text-xs font-medium text-ink">
                      Justificativa ({decisionType === "rejected" ? "obrigatória para rejeição" : "obrigatória para ajustes"}):
                      <textarea
                        data-testid="review-reason-input"
                        rows={2}
                        maxLength={500}
                        value={decisionReason}
                        onChange={(e) => setDecisionReason(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-paper-border p-2 text-xs text-ink focus:outline-none focus:ring-1 focus:ring-action"
                        placeholder="Informe o motivo da decisão..."
                      />
                    </label>
                  </div>
                )}
                <div className="flex gap-2">
                  <Button data-testid="review-confirm-button" disabled={busy} onClick={() => void submitDecision(decisionType)}>
                    Confirmar decisão
                  </Button>
                  <Button variant="ghost" disabled={busy} onClick={() => { setDecisionType(null); setDecisionReason(""); }}>
                    Cancelar
                  </Button>
                </div>
              </div>
            )}

            {/* Ajustes solicitados -> Propor revisão */}
            {selectedReview.state === "changes_requested" && (
              <div className="rounded-xl border border-paper-border bg-amber-50/60 p-3 space-y-2">
                <div className="text-xs font-semibold text-amber-950">Ajustes solicitados pelo revisor</div>
                <div className="text-xs text-ink-subtle">{selectedReview.decision_reason}</div>
                <label className="block text-xs font-medium text-ink pt-2">
                  Novo conteúdo ajustado (criará a versão {selectedReview.artifact_version + 1}):
                  <textarea
                    data-testid="review-revise-input"
                    rows={3}
                    maxLength={50000}
                    value={reviseContent}
                    onChange={(e) => setReviseContent(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-paper-border p-2 text-xs text-ink bg-white focus:outline-none focus:ring-1"
                    placeholder="Insira o texto corrigido para submeter a nova revisão..."
                  />
                </label>
                <Button size="sm" data-testid="review-revise-button" disabled={busy || !reviseContent.trim()} onClick={() => void submitRevision()}>
                  Submeter nova versão
                </Button>
              </div>
            )}

            {/* Histórico de Decisões */}
            {(selectedReview.history ?? []).length > 0 && (
              <div className="border-t border-paper-border pt-3">
                <div className="text-xs font-semibold text-ink-subtle">HISTÓRICO DE DECISÕES NO LEDGER</div>
                <ul className="mt-1 space-y-1 text-xs text-ink-faint">
                  {selectedReview.history!.map((h) => (
                    <li key={h.id}>
                      • <span className="font-medium text-ink">{h.decision}</span> por {h.actor} ({h.created_at})
                      {h.decision_reason && ` — Motivo: ${h.decision_reason}`}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Dialog>
    </Card>
  );
}

"use client";

import { useState } from "react";
import { Button, Card } from "@/components/ui/primitives";
import { LocalApiError, localApiRequest, type LocalSession } from "@/lib/local-api";
import type { Mission, MissionRecord } from "@/lib/mission-contracts";
import { planMissionImport } from "@/lib/mission-import";
import { loadMissions, MISSION_STORAGE_KEY } from "@/lib/mission-store";

type Listed = { dataset: "api_synthetic"; items: Array<MissionRecord & { available_actions?: string[] }>; next_cursor: string | null };

function messageFor(error: unknown): string {
  if (error instanceof LocalApiError) {
    if (error.status === 401) return "Sessão ausente (401). Entre na integração local antes de usar a API.";
    if (error.status === 403) return "Concessão de missão ausente (403). Um grant de Calendar não autoriza esta central.";
    if (error.status === 409) return "Conflito de revisão ou de idempotência (409). Recarregue antes de gravar de novo.";
    return error.message;
  }
  return "A API local sintética não respondeu.";
}

export function MissionApiPanel() {
  const [open, setOpen] = useState(false);
  const [records, setRecords] = useState<Array<MissionRecord & { available_actions?: string[] }>>([]);
  const [notice, setNotice] = useState("API local sintética desligada nesta tela. O modo DEMO continua no navegador.");
  const [busy, setBusy] = useState(false);
  const [previewCount, setPreviewCount] = useState(0);
  const [quarantineCount, setQuarantineCount] = useState(0);
  const [clearLocal, setClearLocal] = useState(false);
  const [pending, setPending] = useState<Mission[]>([]);

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
    } catch (error) {
      setRecords([]);
      setNotice(messageFor(error));
    } finally {
      setBusy(false);
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
      <h2 className="text-base font-semibold text-ink">API local sintética</h2>
      <p className="mt-1 text-sm text-ink-subtle">Fonte de verdade separada do DEMO. Sem fallback silencioso e sem apagar o navegador antes da confirmação.</p>
      <p className="mt-3 text-sm text-ink" role="status">{notice}</p>
      <ul className="mt-3 space-y-3">
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
    </Card>
  );
}

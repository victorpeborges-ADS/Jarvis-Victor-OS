import { afterEach, describe, expect, it, vi } from "vitest";
import { localApiRequest } from "@/lib/local-api";

describe("cliente de revisão e aprovação de artefatos G5", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("consulta fila de revisão e preserva headers de sessão local", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      dataset: "api_synthetic",
      items: [
        {
          id: "rev_test_1",
          mission_id: "mission_123",
          mission_title: "Missão Teste",
          mission_status: "done",
          artifact_id: "artifact_1",
          artifact_version: 1,
          artifact_sha256: "a".repeat(64),
          artifact_title: "Rascunho A",
          artifact_kind: "draft",
          domain_id: "dom_synthetic_a",
          state: "pending",
          decision_reason: null,
          decision_actor: null,
          decided_at: null,
          revision: 1,
          created_at: "2026-09-25T20:00:00Z",
          updated_at: "2026-09-25T20:00:00Z",
        }
      ],
      corrupt: [],
      next_cursor: null,
    }), { status: 200, headers: { "content-type": "application/json" } }));

    vi.stubGlobal("fetch", fetchMock);

    const { data } = await localApiRequest<{ dataset: string; items: unknown[] }>("/real/reviews?limit=20");
    expect(data?.dataset).toBe("api_synthetic");
    expect(data?.items.length).toBe(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/real/reviews?limit=20");
    expect(init.credentials).toBe("include");
  });

  it("submete decisão de aprovação com CSRF e idempotência", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      dataset: "api_synthetic",
      id: "rev_test_1",
      state: "approved",
      revision: 2,
      replayed: false,
    }), { status: 200, headers: { "content-type": "application/json" } }));

    vi.stubGlobal("fetch", fetchMock);

    const { data } = await localApiRequest<{ id: string; state: string }>("/real/reviews/rev_test_1/decide", {
      method: "POST",
      headers: new Headers({ "Content-Type": "application/json", "X-CSRF-Token": "csrf-valid-token" }),
      body: JSON.stringify({
        decision: "approved",
        expected_revision: 1,
        expected_artifact_sha256: "b".repeat(64),
        idempotency_key: "key-decide-001",
      }),
    });

    expect(data?.state).toBe("approved");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/real/reviews/rev_test_1/decide");
    expect(new Headers(init.headers).get("x-csrf-token")).toBe("csrf-valid-token");
  });
});

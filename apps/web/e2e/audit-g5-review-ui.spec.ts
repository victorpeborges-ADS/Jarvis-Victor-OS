import { expect, test, type Page } from "@playwright/test";

const passphrase = process.env.JARVIS_E2E_PASSPHRASE;
const apiOrigin = process.env.JARVIS_E2E_API_ORIGIN ?? "http://127.0.0.1:8000";

async function setupReview(page: Page, title: string) {
  if (!passphrase || passphrase.length < 12) throw new Error("Passphrase sintética ausente.");
  await page.goto("/integrado");
  await page.getByTestId("local-passphrase").fill(passphrase);
  await page.getByTestId("local-login-submit").click();
  await expect(page.getByRole("heading", { name: "Concessões locais" })).toBeVisible();

  const setup = await page.evaluate(async ({ api, missionTitle }) => {
    const sessionResponse = await fetch(`${api}/real/session`, { credentials: "include" });
    const session = await sessionResponse.json() as { csrf_token: string };
    const csrf = session.csrf_token;
    let reviewGrantId = "";
    const activeResponse = await fetch(`${api}/real/grants`, { credentials: "include" });
    if (!activeResponse.ok) throw new Error(`grant inventory: ${activeResponse.status}`);
    const active = await activeResponse.json() as Array<{ id: string; resource_ids: string[]; domain_ids: string[] }>;
    for (const resource of ["mission:read", "mission:write", "mission:review"]) {
      const current = active.find((item) => item.resource_ids.includes(resource) && item.domain_ids.includes("dom_synthetic_a"));
      if (current) {
        if (resource === "mission:review") reviewGrantId = current.id;
        continue;
      }
      const response = await fetch(`${api}/real/grants`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({
          connector: "mission_sim", permission: "read", resource_ids: [resource],
          domain_ids: ["dom_synthetic_a"], expires_at: new Date(Date.now() + 86400000).toISOString()
        })
      });
      if (!response.ok) throw new Error(`grant ${resource}: ${response.status}`);
      const grant = await response.json() as { id: string };
      if (resource === "mission:review") reviewGrantId = grant.id;
    }
    const createdResponse = await fetch(`${api}/real/missions`, {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ title: missionTitle, domain_id: "dom_synthetic_a", idempotency_key: `audit-create-${Date.now()}-${Math.random()}` })
    });
    if (!createdResponse.ok) throw new Error(`mission create: ${createdResponse.status}`);
    const created = await createdResponse.json() as { mission: { id: string } };
    const runResponse = await fetch(`${api}/real/missions/${created.mission.id}/transition`, {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ action: "run_next", expected_revision: 1, idempotency_key: `audit-run-${Date.now()}-${Math.random()}` })
    });
    if (!runResponse.ok) throw new Error(`run step: ${runResponse.status}`);
    const queueResponse = await fetch(`${api}/real/reviews?limit=100`, { credentials: "include" });
    const queue = await queueResponse.json() as { items: Array<{ id: string; mission_id: string }> };
    const reviewId = queue.items.find((item) => item.mission_id === created.mission.id)?.id;
    if (!reviewId) throw new Error("review absent from API queue");
    return { csrf, reviewGrantId, reviewId, missionId: created.mission.id };
  }, { api: apiOrigin, missionTitle: title });
  return setup;
}

async function openReview(page: Page, title: string) {
  await page.goto("/missoes");
  await page.getByTestId("mission-api-open").click();
  await page.getByRole("button", { name: "Atualizar fila de revisão" }).click();
  const card = page.getByTestId("review-card").filter({ hasText: title });
  await expect(card).toBeVisible();
  await card.getByTestId("review-open-button").click();
  await expect(page.getByTestId("review-detail")).toBeVisible();
  return card;
}

test("G5 UI: resposta perdida é reconciliada com estado canônico", async ({ page }) => {
  const title = `Probe UI lost response ${Date.now()}`;
  await setupReview(page, title);
  const card = await openReview(page, title);
  const path = new URL(apiOrigin);
  const keys: string[] = [];
  const statuses: number[] = [];
  await page.route((url) => url.origin === path.origin && url.pathname.endsWith("/decide"), async (route) => {
    keys.push((route.request().postDataJSON() as { idempotency_key: string }).idempotency_key);
    if (statuses.length === 0) {
      const response = await route.fetch();
      statuses.push(response.status());
      await route.abort("failed");
      return;
    }
    await route.continue();
  });
  await page.getByTestId("review-approve-button").click();
  await page.getByTestId("review-confirm-button").click();
  await expect(page.getByTestId("review-modal-notice")).toContainText("O servidor registrou o estado");
  await expect(page.getByTestId("review-decision-form")).toHaveCount(0);
  expect(statuses).toEqual([200]);
  expect(keys.length).toBe(1);

  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Atualizar fila de revisão" }).click();
  await expect(card).toContainText("Aprovado");
  await page.reload();
  await page.getByTestId("mission-api-open").click();
  await page.getByRole("button", { name: "Atualizar fila de revisão" }).click();
  await expect(page.getByTestId("review-card").filter({ hasText: title })).toContainText("Aprovado");
});

test("G5 auditoria independente da UI: grant revogado apresenta 403 e mantém o artefato pendente", async ({ page }) => {
  const title = `Probe UI revoked grant ${Date.now()}`;
  const { csrf, reviewGrantId } = await setupReview(page, title);
  const card = await openReview(page, title);
  const revoke = await page.evaluate(async ({ api, csrfToken, grantId }) => (await fetch(`${api}/real/grants/${grantId}/revoke`, {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken }, body: "{}"
  })).status, { api: apiOrigin, csrfToken: csrf, grantId: reviewGrantId });
  expect(revoke).toBe(200);
  await page.getByTestId("review-approve-button").click();
  await page.getByTestId("review-confirm-button").click();
  await expect(page.getByTestId("review-modal-notice")).toContainText("Concessão ausente (403)");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Atualizar fila de revisão" }).click();
  await expect(card).toContainText("Aguardando revisão");
});

test("G6 UI: conhecimento exige decisão própria e contexto persiste após recarga", async ({ page }) => {
  const title = `Ideia sintética com fonte ${Date.now()}`;
  const { missionId } = await setupReview(page, title);
  await openReview(page, title);
  await page.getByTestId("review-approve-button").click();
  await page.getByTestId("review-confirm-button").click();
  await expect(page.getByTestId("review-modal-notice")).toContainText("confirmada pelo servidor");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Ler missões da API" }).click();
  const knowledge = page.getByTestId("knowledge-card").filter({ hasText: title });
  await expect(knowledge).toContainText("Aguardando revisão");
  const mission = page.getByTestId("mission-api-card").filter({ hasText: title });
  await mission.getByRole("button", { name: "Ver contexto autorizado" }).click();
  await expect(page.getByTestId("context-bundle")).toContainText("aguardando_revisao");
  await knowledge.getByRole("button", { name: "Aprovar conhecimento" }).click();
  await expect(knowledge).toContainText("Aprovado para contexto");
  await mission.getByRole("button", { name: "Ver contexto autorizado" }).click();
  await expect(page.getByTestId("context-bundle")).toContainText(title);
  await mission.getByRole("button", { name: "run_next" }).click();
  await expect(mission).toContainText("revisão 4");
  const contextArtifact = await page.evaluate(async ({ api, id }) => {
    const response = await fetch(`${api}/real/missions/${id}`, { credentials: "include" });
    if (!response.ok) throw new Error(`mission read: ${response.status}`);
    const record = await response.json() as { mission: { artifacts: Array<{ kind: string; content: string; source_refs: Array<{ source_id: string }> }> } };
    return record.mission.artifacts.find((item) => item.kind === "context_bundle");
  }, { api: apiOrigin, id: missionId });
  expect(contextArtifact?.content).toContain(title);
  expect(contextArtifact?.source_refs[0].source_id).toContain("synthetic:knowledge:");
  await page.reload();
  await page.getByTestId("mission-api-open").click();
  await page.getByRole("button", { name: "Ler missões da API" }).click();
  await expect(page.getByTestId("knowledge-card").filter({ hasText: title })).toContainText("Aprovado para contexto");
  await page.getByTestId("mission-api-card").filter({ hasText: title }).getByRole("button", { name: "Ver contexto autorizado" }).click();
  await expect(page.getByTestId("context-bundle")).toContainText(title);
});

test("G6 UI: arquivo fictício escolhido entra somente após duas aprovações", async ({ page }) => {
  const title = `Fonte escolhida ${Date.now()}`;
  const { missionId } = await setupReview(page, title);
  await page.goto("/missoes");
  await page.getByTestId("mission-api-open").click();
  await page.getByRole("button", { name: "Ler missões da API" }).click();
  const sourceSection = page.getByTestId("selected-source-section");
  await sourceSection.getByLabel("Missão de destino").selectOption(missionId);
  await sourceSection.getByTestId("selected-source-file").setInputFiles({
    name: "nota-ficticia.md", mimeType: "text/markdown",
    buffer: Buffer.from("Nota inteiramente fictícia para contexto aprovado.\n"),
  });
  await expect(sourceSection).toContainText("Prévia local");
  await sourceSection.getByRole("checkbox").check();
  await sourceSection.getByRole("button", { name: "Registrar fonte sintética" }).click();
  await expect(sourceSection).toContainText("Fonte sintética registrada");
  const knowledge = page.getByTestId("knowledge-card").filter({ hasText: "Nota inteiramente fictícia" }).filter({ hasText: missionId });
  await expect(knowledge).toContainText("Aguardando revisão");
  const mission = page.getByTestId("mission-api-card").filter({ hasText: title });
  await mission.getByRole("button", { name: "Ver contexto autorizado" }).click();
  await expect(page.getByTestId("context-bundle")).not.toContainText("Nota inteiramente fictícia");
  await page.getByRole("button", { name: "Atualizar fila de revisão" }).click();
  const review = page.getByTestId("review-card").filter({ hasText: "nota-ficticia.md" }).filter({ hasText: title });
  await review.getByTestId("review-open-button").click();
  await expect(page.getByTestId("review-artifact-content")).toContainText("Nota inteiramente fictícia");
  await page.getByTestId("review-approve-button").click();
  await page.getByTestId("review-confirm-button").click();
  await expect(page.getByTestId("review-modal-notice")).toContainText("confirmada pelo servidor");
  await page.keyboard.press("Escape");
  await mission.getByRole("button", { name: "Ver contexto autorizado" }).click();
  await expect(page.getByTestId("context-bundle")).not.toContainText("Nota inteiramente fictícia");
  await knowledge.getByRole("button", { name: "Aprovar conhecimento" }).click();
  await expect(knowledge).toContainText("Aprovado para contexto");
  await mission.getByRole("button", { name: "Ver contexto autorizado" }).click();
  await expect(page.getByTestId("context-bundle")).toContainText("Nota inteiramente fictícia");
});

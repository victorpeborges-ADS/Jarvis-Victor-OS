import { expect, test } from "@playwright/test";

const passphrase = process.env.JARVIS_E2E_PASSPHRASE;
const apiOrigin = process.env.JARVIS_E2E_API_ORIGIN ?? "http://127.0.0.1:8000";

test("aprovação persistente de artefatos na API local sintética (G5)", async ({ page }, info) => {
  if (!passphrase || passphrase.length < 12) throw new Error("Frase sintética de E2E ausente.");

  const domainId = info.project.name === "mobile" ? "dom_synthetic_g" : "dom_synthetic_f";
  const missionTitle = `Missão com aprovação persistente G5 ${info.project.name}`;

  // 1. Log in to local API via /integrado to establish session cookie
  await page.goto("/integrado");
  await page.getByTestId("local-passphrase").fill(passphrase);
  await page.getByTestId("local-login-submit").click();
  await expect(page.getByRole("heading", { name: "Concessões locais" })).toBeVisible();

  // 2. Grant mission:read, mission:write, and mission:review via API directly using session
  const cookieHeader = (await page.context().cookies(apiOrigin)).find((c) => c.name === "jarvis_session");
  expect(cookieHeader).toBeTruthy();

  // Obtain CSRF token from current session
  const sessionRes = await page.evaluate(async (origin) => {
    const res = await fetch(`${origin}/real/session`, { credentials: "include" });
    return res.json() as Promise<{ csrf_token: string }>;
  }, apiOrigin);
  const csrf = sessionRes.csrf_token;
  expect(csrf).toBeTruthy();

  // Create grants for domainId
  await page.evaluate(async ({ origin, token, domain }) => {
    for (const resource of ["mission:read", "mission:write", "mission:review"]) {
      await fetch(`${origin}/real/grants`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
        body: JSON.stringify({
          connector: "mission_sim",
          permission: "read",
          resource_ids: [resource],
          domain_ids: [domain],
          expires_at: new Date(Date.now() + 86400000).toISOString()
        })
      });
    }
  }, { origin: apiOrigin, token: csrf, domain: domainId });

  // 3. Create a mission on the API directly
  const missionRes = await page.evaluate(async ({ origin, token, domain, title }) => {
    const res = await fetch(`${origin}/real/missions`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({
        title,
        domain_id: domain,
        idempotency_key: `e2e-g5-create-${domain}-${Date.now()}`
      })
    });
    return res.json() as Promise<{ mission: { id: string } }>;
  }, { origin: apiOrigin, token: csrf, domain: domainId, title: missionTitle });
  const missionId = missionRes.mission.id;

  // Run first step to produce an artifact draft
  await page.evaluate(async ({ origin, token, id }) => {
    await fetch(`${origin}/real/missions/${id}/transition`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({
        action: "run_next",
        expected_revision: 1,
        idempotency_key: `e2e-g5-run-${id}-${Date.now()}`
      })
    });
  }, { origin: apiOrigin, token: csrf, id: missionId });

  // 4. Navigate to /missoes and open the API panel
  await page.goto("/missoes");
  await page.getByTestId("mission-api-open").click();
  await expect(page.getByTestId("mission-api-panel")).toBeVisible();

  // 5. Click "Atualizar fila de revisão"
  await page.getByRole("button", { name: "Atualizar fila de revisão" }).click();
  const myReviewCard = page.getByTestId("review-card").filter({ hasText: missionTitle });
  await expect(myReviewCard.first()).toBeVisible();
  await expect(myReviewCard.first()).toContainText("Aguardando revisão");

  // 6. Open inspection dialog
  await myReviewCard.first().getByTestId("review-open-button").click();
  await expect(page.getByTestId("review-detail")).toBeVisible();
  await expect(page.getByTestId("review-artifact-content")).toBeVisible();
  await expect(page.getByTestId("review-artifact-content")).toContainText("Código determinístico v1.0.0");
  const originalReviewId = await page.getByTestId("review-detail").getAttribute("data-review-id");
  expect(originalReviewId).toBeTruthy();

  // 7. Request changes flow
  await page.getByTestId("review-changes-button").click();
  await expect(page.getByTestId("review-decision-form")).toBeVisible();

  // Submitting without reason fails with warning
  await page.getByTestId("review-confirm-button").click();
  await expect(page.getByTestId("review-modal-notice")).toContainText("Justificativa obrigatória");

  // Fill reason and submit
  await page.getByTestId("review-reason-input").fill("Favor ajustar o formato de apresentação.");
  await page.getByTestId("review-confirm-button").click();

  // Notice confirms decision and shows changes requested state
  await expect(page.getByTestId("review-modal-notice")).toContainText("changes_requested");
  await expect(page.getByTestId("review-revise-input")).toBeVisible();

  // 8. Submit revised version 2
  await page.getByTestId("review-revise-input").fill("Conteúdo revisado e formatado com sucesso.");
  await page.getByTestId("review-revise-button").click();
  await expect(page.getByTestId("review-modal-notice")).toContainText("Versão 2");
  await expect(page.getByTestId("review-detail")).toHaveAttribute("data-review-version", "2");
  await expect(page.getByTestId("review-detail")).not.toHaveAttribute("data-review-id", originalReviewId!);
  const revisedReviewId = await page.getByTestId("review-detail").getAttribute("data-review-id");
  expect(revisedReviewId).toBeTruthy();
  if (!revisedReviewId) throw new Error("revised review ID missing");
  expect(revisedReviewId).not.toBe(originalReviewId);

  // 9. Approve the revised version
  await page.getByTestId("review-approve-button").click();
  await page.getByTestId("review-confirm-button").click();
  await expect(page.getByTestId("review-modal-notice")).toContainText("approved");
  const approvedVersion = await page.evaluate(async ({ origin, id }) => {
    const response = await fetch(`${origin}/real/reviews/${encodeURIComponent(id)}`, { credentials: "include" });
    if (!response.ok) throw new Error(`revised review read: ${response.status}`);
    const review = await response.json() as { id: string; artifact_version: number; state: string };
    return { id: review.id, version: review.artifact_version, state: review.state };
  }, { origin: apiOrigin, id: revisedReviewId });
  expect(approvedVersion).toEqual({ id: revisedReviewId, version: 2, state: "approved" });

  // Close dialog and verify queue state
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("review-detail")).toHaveCount(0);
  await page.getByRole("button", { name: "Atualizar fila de revisão" }).click();
  const approvedCard = page.getByTestId("review-card").filter({ hasText: missionTitle }).filter({ hasText: "Aprovado" });
  await expect(approvedCard).toBeVisible();

  // 10. Reload the page and verify approval persists in SQLite
  await page.reload();
  await page.getByTestId("mission-api-open").click();
  await page.getByRole("button", { name: "Atualizar fila de revisão" }).click();
  await expect(page.getByTestId("review-card").filter({ hasText: missionTitle }).filter({ hasText: "Aprovado" })).toBeVisible();
});

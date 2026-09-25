import { createServer } from "node:http";
import { once } from "node:events";
import { describe, expect, it } from "vitest";
import { assertPortAvailable, createReadinessToken, waitForOwnedApi } from "../scripts/e2e-api-readiness.mjs";

async function listen(server, host, port = 0) {
  server.listen(port, host);
  await once(server, "listening");
  return server.address().port;
}

describe("readiness do runner E2E", () => {
  it("recusa um servidor falso que vence a corrida entre o pré-voo e o spawn da API", async () => {
    const host = "127.0.0.1";
    const reservation = createServer();
    const port = await listen(reservation, host);
    await new Promise((resolve, reject) => reservation.close((error) => error ? reject(error) : resolve()));
    await assertPortAvailable(port, host, "API");

    const fakeApi = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ status: "ok", demo: true }));
    });
    await listen(fakeApi, host, port);
    try {
      const runnerChild = { exitCode: null };
      await expect(waitForOwnedApi({ child: runnerChild, origin: `http://${host}:${port}`, token: createReadinessToken(), timeoutMs: 1000, intervalMs: 1 }))
        .rejects.toThrow("não provou pertencer ao runner iniciado");
    } finally {
      await new Promise((resolve, reject) => fakeApi.close((error) => error ? reject(error) : resolve()));
    }
  });
});

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import net from "node:net";

export function assertPortAvailable(port, host, label) {
  return new Promise((resolvePromise, reject) => {
    const server = net.createServer();
    server.once("error", () => reject(new Error(`Porta ${label} ${port} já está ocupada; escolha outra porta loopback para o E2E.`)));
    server.listen(port, host, () => server.close((error) => error ? reject(error) : resolvePromise()));
  });
}

export function createReadinessToken() {
  return randomBytes(32).toString("base64url");
}

function expectedProof(token, nonce) {
  return createHmac("sha256", token).update(nonce, "ascii").digest();
}

export function matchesReadinessProof(token, nonce, received) {
  if (!/^[0-9a-f]{64}$/.test(nonce) || !/^[0-9a-f]{64}$/.test(received ?? "")) return false;
  const expected = expectedProof(token, nonce);
  const actual = Buffer.from(received, "hex");
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

export async function waitForOwnedApi({ child, origin, token, fetchImpl = fetch, timeoutMs = 60_000, intervalMs = 250 }) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`API sintética encerrou antes de ficar pronta (exit ${child.exitCode}).`);
    const nonce = randomBytes(32).toString("hex");
    try {
      const response = await fetchImpl(`${origin}/health`, {
        headers: { "x-jarvis-e2e-nonce": nonce },
        signal: AbortSignal.timeout(1000)
      });
      if (response.ok) {
        const proof = response.headers.get("x-jarvis-e2e-ready-proof");
        if (!matchesReadinessProof(token, nonce, proof)) {
          throw new Error("A API na porta E2E respondeu, mas não provou pertencer ao runner iniciado.");
        }
        return;
      }
    } catch (error) {
      if (error instanceof Error && error.message.includes("não provou pertencer")) throw error;
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, intervalMs));
  }
  throw new Error("Tempo esgotado ao iniciar a API sintética em loopback.");
}

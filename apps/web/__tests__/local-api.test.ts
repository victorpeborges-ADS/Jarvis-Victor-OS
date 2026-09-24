import { afterEach, describe, expect, it, vi } from "vitest";
import { LOCAL_API_BASE, LocalApiError, localApiRequest, resolveLocalApiBase } from "@/lib/local-api";

describe("cliente tipado da API local", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("usa loopback e rejeita endpoints externos ou com credenciais", () => {
    expect(LOCAL_API_BASE).toBe("http://localhost:8000");
    expect(resolveLocalApiBase("http://localhost:8123")).toBe("http://localhost:8123");
    expect(resolveLocalApiBase("http://[::1]:8000")).toBe("http://[::1]:8000");
    expect(() => resolveLocalApiBase("https://api.example.test")).toThrow(/loopback/i);
    expect(() => resolveLocalApiBase("http://user:password@127.0.0.1:8000")).toThrow(/loopback/i);
  });

  it("envia cookie, não armazena resposta e mantém headers CSRF", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200, headers: { "content-type": "application/json" }
    }));
    vi.stubGlobal("fetch", fetchMock);
    await localApiRequest("/real/calendar-sim/state", {
      method: "PUT",
      headers: new Headers({ "Content-Type": "application/json", "X-CSRF-Token": "csrf-synthetic-test" }),
      body: "{}"
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/real/calendar-sim/state");
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(new Headers(init.headers).get("x-csrf-token")).toBe("csrf-synthetic-test");
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
  });

  it("não inclui payloads de erro ou credenciais na mensagem da interface", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: "passphrase-super-secreta título privado"
    }), { status: 403, headers: { "content-type": "application/json" } })));
    await expect(localApiRequest("/real/events")).rejects.toMatchObject({
      name: "LocalApiError", status: 403
    });
    try {
      await localApiRequest("/real/events");
    } catch (error) {
      expect(error).toBeInstanceOf(LocalApiError);
      expect((error as Error).message).not.toContain("passphrase-super-secreta");
      expect((error as Error).message).not.toContain("título privado");
    }
  });
});

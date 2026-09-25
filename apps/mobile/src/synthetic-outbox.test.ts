import { describe, expect, it } from "vitest";
import { loadSyntheticOutbox, OUTBOX_KEY, saveSyntheticCapture, type StorageLike } from "./synthetic-outbox";

class MemoryStorage implements StorageLike {
  values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

describe("outbox local sintética mobile", () => {
  it("salva somente capturas rotuladas, limita texto e retém no máximo 20", () => {
    const storage = new MemoryStorage();
    for (let index = 0; index < 22; index += 1) {
      saveSyntheticCapture(storage, `  captura ${index}  `, "2026-09-25T00:00:00Z", `capture_${index}`);
    }
    const list = loadSyntheticOutbox(storage);
    expect(list).toHaveLength(20);
    expect(list[0]).toMatchObject({ id: "capture_21", text: "captura 21", synthetic: true });
    expect(list[19].id).toBe("capture_2");
    expect(saveSyntheticCapture(storage, "  ", "now", "empty")).toBeNull();
    expect(JSON.parse(storage.getItem(OUTBOX_KEY) ?? "[]")).toHaveLength(20);
  });

  it("descarta JSON malformado e entradas sem o marcador sintético", () => {
    const storage = new MemoryStorage();
    storage.setItem(OUTBOX_KEY, "{");
    expect(loadSyntheticOutbox(storage)).toEqual([]);
    storage.setItem(OUTBOX_KEY, JSON.stringify([
      { id: "real", text: "não carregar", created_at: "now", synthetic: false },
      { id: "demo", text: "teste", created_at: "now", synthetic: true },
    ]));
    expect(loadSyntheticOutbox(storage).map((item) => item.id)).toEqual(["demo"]);
  });
});

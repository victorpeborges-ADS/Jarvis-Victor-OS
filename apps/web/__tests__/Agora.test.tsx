import { render, screen } from "@testing-library/react";
import AgoraPage from "../app/page";
import {
  greetingFromHour,
  formatMinutesUntil,
  commitmentsToday,
  messagesToday,
  syncStatusLabel,
  DEMO_NOW
} from "../lib/demo";

describe("Agora — jornada 1: entender o dia em 5s", () => {
  it("mostra próximo compromisso com CTA de evidência sob demanda", () => {
    render(<AgoraPage />);
    expect(screen.getAllByText(/PRÓXIMO COMPROMISSO/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Daily MedSyn — revisão sprint/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Por que isso importa/i })).toBeInTheDocument();
    expect(screen.queryByText(/^EVIDÊNCIA$/)).not.toBeInTheDocument();
  });

  it("mostra prioridade essencial e alerta com consequência", () => {
    render(<AgoraPage />);
    expect(screen.getAllByText(/PRIORIDADE ESSENCIAL/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Finalizar slides demo MedSyn/i)).toBeInTheDocument();
    expect(screen.getAllByText(/ALERTA COM CONSEQUÊNCIA/i).length).toBeGreaterThan(0);
  });

  it("exibe alerta de fonte desatualizada e sinalização de demonstração", () => {
    render(<AgoraPage />);
    expect(screen.getAllByText(/Demonstração/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Dados possivelmente desatualizados/i)).toBeInTheDocument();
  });

  it("separa compromissos de mensagens na timeline", () => {
    render(<AgoraPage />);
    expect(screen.getByText(/Linha do tempo — hoje/i)).toBeInTheDocument();
    expect(screen.getByText(/COMPROMISSOS · 3/i)).toBeInTheDocument();
    expect(screen.getByText(/MENSAGENS · 2/i)).toBeInTheDocument();
  });
});

describe("Tempo DEMO — coerência", () => {
  it("saudação alinhada ao relógio DEMO (09h = Bom dia)", () => {
    expect(greetingFromHour(DEMO_NOW)).toBe("Bom dia");
    expect(greetingFromHour("2026-09-23T14:00:00-03:00")).toBe("Boa tarde");
    expect(greetingFromHour("2026-09-23T20:00:00-03:00")).toBe("Boa noite");
  });

  it("minutos até o próximo compromisso usam DEMO_NOW", () => {
    expect(formatMinutesUntil("2026-09-23T09:30:00-03:00")).toBe("em 30 min");
  });

  it("contagens separam commitment e communication", () => {
    expect(commitmentsToday()).toHaveLength(3);
    expect(messagesToday()).toHaveLength(2);
  });

  it("nunca rotula sync como connected cru", () => {
    expect(syncStatusLabel("connected")).toBe("exemplo · atualizado");
    expect(syncStatusLabel("stale")).toBe("exemplo · desatualizado");
    expect(syncStatusLabel("connected")).not.toMatch(/^connected$/);
  });
});

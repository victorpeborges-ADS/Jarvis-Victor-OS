import { render, screen } from "@testing-library/react";
import AgoraPage from "../app/page";

describe("Agora — jornada 1: entender o dia em 5s", () => {
  it("mostra próximo compromisso com evidência", () => {
    render(<AgoraPage />);
    expect(screen.getAllByText(/PRÓXIMO COMPROMISSO/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Daily MedSyn — revisão sprint/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/EVIDÊNCIA/i).length).toBeGreaterThan(0);
  });

  it("mostra prioridade essencial e alerta com consequência", () => {
    render(<AgoraPage />);
    expect(screen.getAllByText(/PRIORIDADE ESSENCIAL/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Finalizar slides demo MedSyn/i)).toBeInTheDocument();
    expect(screen.getAllByText(/ALERTA COM CONSEQUÊNCIA/i).length).toBeGreaterThan(0);
  });

  it("exibe estado stale do Drive e sinalização DEMO", () => {
    render(<AgoraPage />);
    expect(screen.getAllByText(/DEMO/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Dados possivelmente desatualizados/i)).toBeInTheDocument();
  });

  it("lista timeline compacta e captura vinculada a CRIVO", () => {
    render(<AgoraPage />);
    expect(screen.getByText(/Linha do tempo — hoje/i)).toBeInTheDocument();
    expect(screen.getByText(/Ideia CRIVO: triagem por similaridade/i)).toBeInTheDocument();
  });
});

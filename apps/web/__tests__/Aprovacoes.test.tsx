import { render, screen, fireEvent } from "@testing-library/react";
import AprovacoesPage from "../app/aprovacoes/page";

describe("Aprovações — jornada 2: conflito sem escrita externa", () => {
  it("mostra proposta de conflito com diff e alternativas", () => {
    render(<AprovacoesPage />);
    expect(screen.getByText(/CENTRAL DE APROVAÇÃO/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Mover Academia para 17h/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Alternativa A/i)).toBeInTheDocument();
    expect(screen.getByText(/DIFF EM LINGUAGEM NATURAL/i)).toBeInTheDocument();
  });

  it("aprovação é rascunho local sem escrita externa", () => {
    render(<AprovacoesPage />);
    fireEvent.click(screen.getByText(/Aprovar Alt A — rascunho local/i));
    expect(screen.getByText(/Aprovado — nenhuma escrita externa/i)).toBeInTheDocument();
    expect(screen.getByText(/idempotente/i)).toBeInTheDocument();
  });
});

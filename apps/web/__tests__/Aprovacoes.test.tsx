import { render, screen, fireEvent } from "@testing-library/react";
import AprovacoesPage from "../app/aprovacoes/page";

describe("Aprovações — jornada 2: conflito sem escrita externa", () => {
  it("mostra proposta de conflito com diff e alternativas selecionáveis", () => {
    render(<AprovacoesPage />);
    expect(screen.getByText(/CENTRAL DE APROVAÇÃO/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Mover Academia para 17h/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Alternativa A/i)).toBeInTheDocument();
    expect(screen.getByText(/Alternativa B/i)).toBeInTheDocument();
    expect(screen.getByText(/DIFF EM LINGUAGEM NATURAL/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Antecipar academia/i })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Manter academia 18h/i })).not.toBeChecked();
  });

  it("permite selecionar Alternativa B e aprovar como rascunho local", () => {
    render(<AprovacoesPage />);
    fireEvent.click(screen.getByRole("radio", { name: /Manter academia 18h/i }));
    expect(screen.getByRole("radio", { name: /Manter academia 18h/i })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: /Aprovar Alt B — rascunho local/i }));
    expect(screen.getByText(/Aprovado — rascunho local \(Alt B\)/i)).toBeInTheDocument();
    expect(screen.queryByText(/idempotente/i)).not.toBeInTheDocument();
  });

  it("esconde detalhes técnicos até expansão", () => {
    render(<AprovacoesPage />);
    expect(screen.queryByText(/idem_dec001_act001/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Mostrar detalhes técnicos/i }));
    expect(screen.getByText(/idem_dec001_act001/i)).toBeInTheDocument();
  });

  it("distingue rascunho local de alteração externa", () => {
    render(<AprovacoesPage />);
    expect(screen.getAllByText(/Rascunho local/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Alteração externa/i).length).toBeGreaterThan(0);
  });
});

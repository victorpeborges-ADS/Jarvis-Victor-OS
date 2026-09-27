import { render, screen, fireEvent } from "@testing-library/react";
import AprovacoesPage from "../app/aprovacoes/page";

describe("Aprovações — jornada 2: conflito sem escrita externa", () => {
  it("mostra proposta de conflito com diff e alternativas selecionáveis", () => {
    render(<AprovacoesPage />);
    expect(screen.getByText(/DECISÕES/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Mover Academia para 17h/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Alternativa A/i)).toBeInTheDocument();
    expect(screen.getByText(/Alternativa B/i)).toBeInTheDocument();
    expect(screen.getByText(/RESUMO DA MUDANÇA/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Antecipar academia/i })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Manter academia 18h/i })).not.toBeChecked();
  });

  it("permite selecionar Alternativa B e aprovar como rascunho local", () => {
    render(<AprovacoesPage />);
    fireEvent.click(screen.getByRole("radio", { name: /Manter academia 18h/i }));
    expect(screen.getByRole("radio", { name: /Manter academia 18h/i })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: /Aprovar sugestão B — somente nesta tela/i }));
    expect(screen.getByText(/Sugestão aprovada nesta demonstração \(opção B\)/i)).toBeInTheDocument();
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
    expect(screen.getByText(/As escolhas nesta página são demonstrações locais/i)).toBeInTheDocument();
    expect(screen.getByText(/Nenhuma conta ou agenda é alterada/i)).toBeInTheDocument();
  });
});

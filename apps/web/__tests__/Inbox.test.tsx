import { render, screen, fireEvent } from "@testing-library/react";
import InboxPage from "../app/inbox/page";

describe("Inbox — jornada 3: captura sem ação externa", () => {
  it("renderiza captura rápida com classificação em destaque", () => {
    render(<InboxPage />);
    expect(screen.getByText(/NOVA CAPTURA/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Classificar e salvar/i })).toBeInTheDocument();
    expect(screen.getByText(/Ideia CRIVO: triagem por similaridade/i)).toBeInTheDocument();
    expect(screen.getByText(/classificado/i)).toBeInTheDocument();
  });

  it("permite capturar nova ideia e mostra feedback pós-captura", () => {
    render(<InboxPage />);
    const textarea = screen.getByPlaceholderText(/organizar referências do projeto CRIVO/i);
    fireEvent.change(textarea, { target: { value: "Nova ideia teste sobre embeddings" } });
    fireEvent.click(screen.getByRole("button", { name: /Classificar e salvar/i }));
    expect(screen.getByText(/Nova ideia teste/i)).toBeInTheDocument();
    expect(screen.getByText(/Captura classificada e salva/i)).toBeInTheDocument();
    expect(screen.getByText(/Nenhuma reunião ou e-mail foi criado/i)).toBeInTheDocument();
  });

  it("mostra estado vazio ao filtrar domínio sem itens", () => {
    render(<InboxPage />);
    fireEvent.click(screen.getByRole("button", { name: /^MedSyn$/i }));
    expect(screen.getByText(/Nenhum item neste filtro/i)).toBeInTheDocument();
  });
});

import { render, screen, fireEvent } from "@testing-library/react";
import InboxPage from "../app/inbox/page";

describe("Inbox — jornada 3: captura sem ação externa", () => {
  it("renderiza captura rápida com classificação", () => {
    render(<InboxPage />);
    expect(screen.getByText(/NOVA CAPTURA — JORNADA 3/i)).toBeInTheDocument();
    expect(screen.getByText(/Classificar e salvar/i)).toBeInTheDocument();
    expect(screen.getByText(/Ideia CRIVO: triagem por similaridade/i)).toBeInTheDocument();
  });

  it("permite capturar nova ideia e vincular a CRIVO", () => {
    render(<InboxPage />);
    const textarea = screen.getByPlaceholderText(/Ideia CRIVO/i);
    fireEvent.change(textarea, { target: { value: "Nova ideia teste sobre embeddings" } });
    fireEvent.click(screen.getByText("Classificar e salvar"));
    expect(screen.getByText(/Nova ideia teste/i)).toBeInTheDocument();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { Button } from "../components/ui/primitives";

describe("Button — proteção contra envio involuntário", () => {
  it("não envia formulários quando o tipo não é explicitamente informado", () => {
    const submit = vi.fn((event: React.FormEvent) => event.preventDefault());
    const action = vi.fn();
    render(
      <form onSubmit={submit}>
        <Button onClick={action}>Abrir detalhes</Button>
        <Button type="submit">Enviar dados</Button>
      </form>
    );

    const actionButton = screen.getByRole("button", { name: "Abrir detalhes" });
    expect(actionButton).toHaveAttribute("type", "button");
    fireEvent.click(actionButton);
    expect(action).toHaveBeenCalledOnce();
    expect(submit).not.toHaveBeenCalled();
  });

  it("preserva o envio intencional ao especificar type=submit", () => {
    const submit = vi.fn((event: React.FormEvent) => event.preventDefault());
    render(
      <form onSubmit={submit}>
        <Button type="submit">Enviar dados</Button>
      </form>
    );
    const submitButton = screen.getByRole("button", { name: "Enviar dados" });
    expect(submitButton).toHaveAttribute("type", "submit");
    fireEvent.click(submitButton);
    expect(submit).toHaveBeenCalledOnce();
  });

  it("preserva o tipo reset explicitamente solicitado", () => {
    render(
      <form>
        <input aria-label="Nome" defaultValue="original" />
        <Button type="reset">Limpar</Button>
      </form>
    );
    const resetButton = screen.getByRole("button", { name: "Limpar" });
    expect(resetButton).toHaveAttribute("type", "reset");
  });
});

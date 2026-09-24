import { render, screen } from "@testing-library/react";
import AprovacoesPage from "../app/aprovacoes/page";
import { SELECTED_CARD_BACKGROUND, SELECTED_CARD_TEXT } from "../lib/contrast-tokens";

function channel(value: number) {
  const ratio = value / 255;
  return ratio <= 0.04045 ? ratio / 12.92 : ((ratio + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string) {
  const [red, green, blue] = [0, 2, 4].map((index) => parseInt(hex.slice(index, index + 2), 16));
  return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue);
}

function contrast(foreground: string, background: string) {
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

describe("contraste do cartão selecionado em Aprovações", () => {
  const selectedBackground = SELECTED_CARD_BACKGROUND.replace("#", "");
  const selectedText = SELECTED_CARD_TEXT.replace("#", "");

  it("mantém margem acima de 4,5:1 no fundo real do cartão", () => {
    expect(contrast(selectedText, selectedBackground)).toBeGreaterThanOrEqual(5);
  });

  it("usa a cor segura só no impacto da alternativa selecionada", () => {
    render(<AprovacoesPage />);
    expect(screen.getByText("Chega 18h30, buffer 30min antes da entrega").className).toContain("text-ink-onSelected");
    expect(screen.getByText("Buffer 15min, risco moderado").className).toContain("text-ink-subtle");
  });
});

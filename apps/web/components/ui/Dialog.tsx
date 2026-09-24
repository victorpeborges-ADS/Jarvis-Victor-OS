"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "[tabindex]:not([tabindex='-1'])"
].join(",");

function focusableWithin(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => !element.hasAttribute("disabled") && element.tabIndex !== -1 && element.getClientRects().length > 0
  );
}

function restoreFocus(trigger: HTMLElement | null) {
  if (trigger?.isConnected) {
    trigger.focus();
    return;
  }
  const main = document.getElementById("conteudo");
  if (!main) return;
  if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
  main.focus();
}

export function Dialog({
  open,
  onClose,
  titleId,
  label,
  children
}: {
  open: boolean;
  onClose: () => void;
  titleId: string;
  label: string;
  children: React.ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const background = Array.from(document.querySelectorAll<HTMLElement>("header, main, aside, nav"));
    const previousOverflow = document.body.style.overflow;
    background.forEach((node) => node.setAttribute("inert", ""));
    document.body.style.overflow = "hidden";

    const panel = panelRef.current;
    const initial = focusableWithin(panel)[0] ?? panel;
    initial?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusableWithin(panelRef.current);
      if (items.length === 0) {
        event.preventDefault();
        panelRef.current?.focus();
        return;
      }
      const current = document.activeElement;
      const index = items.findIndex((item) => item === current);
      const next = event.shiftKey ? (index <= 0 ? items.length - 1 : index - 1) : index === items.length - 1 || index === -1 ? 0 : index + 1;
      if (event.shiftKey ? index <= 0 : index === items.length - 1 || index === -1) {
        event.preventDefault();
        items[next]?.focus();
      }
    }

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      background.forEach((node) => node.removeAttribute("inert"));
      document.body.style.overflow = previousOverflow;
      restoreFocus(trigger);
    };
  }, [open]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex">
      <button type="button" className="absolute inset-0 bg-ink/20" aria-label="Dispensar painel" onClick={onClose} tabIndex={-1} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-label={label}
        tabIndex={-1}
        className="relative ml-auto flex h-full w-full max-w-[420px] flex-col bg-white shadow-elevated pb-[env(safe-area-inset-bottom)]"
      >
        {children}
      </div>
    </div>,
    document.body
  );
}

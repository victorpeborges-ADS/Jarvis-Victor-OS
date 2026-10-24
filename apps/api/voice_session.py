"""Contrato de voz e de tela, sem microfone e sem observação do app.

O gesto é explícito e em primeiro plano. Não há wake word nem escuta contínua.
A transcrição não envia mensagem nem aprova efeito. Cancelar não grava captura.
Teste acústico e teste de tela permanecem bloqueados.
"""

from __future__ import annotations

import secrets
import math
import re

ACOUSTIC_TEST = "BLOCKED"
SCREEN_TEST = "BLOCKED"
WAKE_WORD = "disabled"
LISTEN_LIMIT_SECONDS = 30
_STATES = {
    "idle": "em espera",
    "starting": "iniciando",
    "listening": "ouvindo",
    "transcribing": "transcrevendo",
    "generating": "gerando",
    "speaking": "falando",
    "failed": "falha",
    "cancelled": "cancelado",
}


class VoiceError(Exception):
    pass


class VoiceSession:
    def __init__(self) -> None:
        self.state = "idle"
        self.indicator = False
        self.foreground = False
        self.focused = True
        self.turn_id = ""
        self.partial = ""
        self.final = ""
        self.confirmed = False
        self.sent = False
        self.capture_saved = False
        self.audio_token = ""
        self.interrupted = False
        self.reduced_motion = True
        self.focus_visible = True
        self.elapsed = 0.0
        self.reason = ""

    def begin(self, *, foreground: bool) -> None:
        if not foreground:
            raise VoiceError("voz recusada")
        if self.state not in {"idle", "failed", "cancelled"}:
            raise VoiceError("turno anterior ainda ativo")
        self.state = "starting"
        self.indicator = True
        self.foreground = True
        self.focused = True
        self.turn_id = secrets.token_hex(8)
        self.partial = ""
        self.final = ""
        self.confirmed = False
        self.sent = False
        self.capture_saved = False
        self.audio_token = ""
        self.interrupted = False
        self.elapsed = 0.0
        self.reason = ""

    def listen(self) -> None:
        if self.state != "starting" or not self.foreground or not self.focused or not self.indicator:
            raise VoiceError("voz recusada")
        self.state = "listening"

    def lose_focus(self) -> None:
        self.focused = False
        if self.state in {"starting", "listening", "transcribing", "generating", "speaking"}:
            self._fail("foco_perdido")

    def advance(self, seconds: float) -> None:
        if self.state != "listening":
            return
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise VoiceError("duração inválida")
        self.elapsed += seconds
        if self.elapsed > LISTEN_LIMIT_SECONDS:
            self._fail("limite_de_escuta")

    def transcribe(self, text: str, *, partial: bool) -> None:
        if self.state not in {"listening", "transcribing"} or not isinstance(text, str) or text == "":
            raise VoiceError("voz recusada")
        self.state = "transcribing"
        self.sent = False
        if partial:
            self.partial = text
            return
        self.partial = ""
        self.final = text

    def confirm_transcript(self) -> None:
        if self.state != "transcribing" or self.final == "":
            raise VoiceError("voz recusada")
        self.confirmed = True
        self.sent = False

    def generate(self) -> None:
        if self.state != "transcribing" or not self.confirmed:
            raise VoiceError("voz recusada")
        self.state = "generating"
        self.sent = False

    def speak(self, turn_id: str) -> None:
        if self.state != "generating" or turn_id != self.turn_id:
            raise VoiceError("voz recusada")
        self.audio_token = secrets.token_hex(4)
        self.state = "speaking"

    def interrupt(self) -> None:
        if self.state != "speaking":
            raise VoiceError("voz recusada")
        self.audio_token = ""
        self.interrupted = True
        self.state = "idle"
        self.indicator = False

    def cancel(self) -> None:
        self.state = "cancelled"
        self.foreground = False
        self.partial = ""
        self.final = ""
        self.confirmed = False
        self.audio_token = ""
        self.indicator = False
        self.capture_saved = False
        self.sent = False

    def send_message(self) -> None:
        raise VoiceError("transcrição não envia mensagem")

    def approve_effect(self, utterance: str) -> None:
        raise VoiceError("voz não aprova efeito")

    def wake(self) -> str:
        return WAKE_WORD

    def state_text(self) -> str:
        return _STATES[self.state]

    def _fail(self, reason: str) -> None:
        self.state = "failed"
        self.reason = reason
        self.partial = ""
        self.final = ""
        self.indicator = False
        self.capture_saved = False
        self.sent = False


def observe_screen() -> dict[str, str | bool]:
    return {
        "status": SCREEN_TEST,
        "continuous": False,
        "mask": "obrigatoria",
        "preview": "nada sai",
    }


def prepare_screen_preview(fixture_text: str, masked_values: tuple[str, ...]) -> dict[str, str | bool]:
    """Prepara preview somente de fixture textual; não captura nem observa a tela."""
    if not isinstance(fixture_text, str) or not isinstance(masked_values, tuple):
        raise VoiceError("fixture de preview inválida")
    preview = fixture_text
    for value in masked_values:
        if not isinstance(value, str) or not value:
            raise VoiceError("máscara inválida")
        preview = re.sub(re.escape(value), "[MASCARADO]", preview, flags=re.IGNORECASE)
    return {"status": "fixture_preview", "continuous": False, "preview": preview, "capture": False}


def browser_action(kind: str, *, target: str = "") -> dict[str, str | bool]:
    if kind == "navigate":
        if not isinstance(target, str) or not target:
            raise VoiceError("destino de navegação ausente")
        return {"status": "draft", "operation": kind, "target": target, "sent": False}
    if kind == "fill":
        if not isinstance(target, str) or not re.fullmatch(r"role:[a-z-]+\|name:.+", target):
            raise VoiceError("preenchimento exige alvo semântico role/name")
        return {"status": "draft", "operation": kind, "target": target, "sent": False}
    raise VoiceError("envio separado da navegação")


def native_action() -> dict[str, str]:
    return {"status": "BLOCKED", "reason": "revalidacao_de_foco"}

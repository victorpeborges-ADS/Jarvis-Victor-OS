"""Estados de voz. Não abre microfone, não observa a tela e não envia mensagem."""

from __future__ import annotations

from pathlib import Path

import pytest

from voice_session import (
    ACOUSTIC_TEST,
    SCREEN_TEST,
    WAKE_WORD,
    VoiceError,
    VoiceSession,
    browser_action,
    native_action,
    observe_screen,
    prepare_screen_preview,
)


def _ready() -> VoiceSession:
    session = VoiceSession()
    session.begin(foreground=True)
    session.listen()
    return session


def test_microphone_requires_an_explicit_foreground_gesture():
    session = VoiceSession()
    with pytest.raises(VoiceError):
        session.listen()
    with pytest.raises(VoiceError):
        session.begin(foreground=False)
    assert session.state == "idle"
    assert session.indicator is False
    session.begin(foreground=True)
    assert session.state == "starting"
    assert session.indicator is True
    assert session.state_text() == "iniciando"


def test_transcript_does_not_send_or_approve_and_cancel_discards_it():
    session = _ready()
    session.transcribe("rascunho", partial=True)
    assert session.state == "transcribing"
    assert session.sent is False
    with pytest.raises(VoiceError):
        session.generate()
    session.transcribe("texto final", partial=False)
    session.confirm_transcript()
    session.generate()
    assert session.state == "generating"
    assert session.sent is False
    assert session.capture_saved is False
    with pytest.raises(VoiceError, match="não envia"):
        session.send_message()
    with pytest.raises(VoiceError, match="não aprova"):
        session.approve_effect("sim")
    session.cancel()
    assert session.state == "cancelled"
    assert session.final == ""
    assert session.capture_saved is False
    assert session.state_text() == "cancelado"


def test_old_audio_is_interrupted_and_turns_do_not_mix():
    session = _ready()
    session.transcribe("texto final", partial=False)
    session.confirm_transcript()
    session.generate()
    old_turn = session.turn_id
    session.speak(old_turn)
    assert session.state == "speaking"
    token = session.audio_token
    session.interrupt()
    assert session.interrupted is True
    assert session.audio_token == ""
    assert token != ""
    session.begin(foreground=True)
    new_turn = session.turn_id
    assert new_turn != old_turn
    session.listen()
    session.transcribe("outro turno", partial=False)
    session.confirm_transcript()
    session.generate()
    with pytest.raises(VoiceError):
        session.speak(old_turn)
    session.speak(new_turn)
    assert session.state == "speaking"


def test_focus_loss_and_listen_limit_stop_without_capture():
    session = _ready()
    session.lose_focus()
    assert session.state == "failed"
    assert session.reason == "foco_perdido"
    assert session.capture_saved is False
    limited = _ready()
    limited.advance(31)
    assert limited.state == "failed"
    assert limited.reason == "limite_de_escuta"
    assert limited.partial == ""
    for invalid in (-1, float("nan"), float("inf")):
        with pytest.raises(VoiceError, match="duração inválida"):
            _ready().advance(invalid)


def test_restarting_turn_resets_focus_and_capture_state_and_active_turn_cannot_be_replaced():
    session = _ready()
    with pytest.raises(VoiceError, match="ainda ativo"):
        session.begin(foreground=True)
    session.lose_focus()
    session.begin(foreground=True)
    assert session.focused is True
    assert session.capture_saved is False
    session.listen()


def test_screen_fixture_preview_masks_content_without_screen_capture():
    result = prepare_screen_preview("contato ana@example.test e chave xyz", ("ana@example.test", "xyz"))
    assert result == {
        "status": "fixture_preview",
        "continuous": False,
        "preview": "contato [MASCARADO] e chave [MASCARADO]",
        "capture": False,
    }
    with pytest.raises(VoiceError):
        prepare_screen_preview("texto", ("",))


def test_wake_word_screen_and_browser_send_stay_blocked():
    session = VoiceSession()
    assert session.wake() == WAKE_WORD == "disabled"
    assert session.state == "idle"
    observed = observe_screen()
    assert observed["status"] == SCREEN_TEST == "BLOCKED"
    assert observed["continuous"] is False
    assert observed["mask"] == "obrigatoria"
    draft = browser_action("navigate", target="https://fixture.invalid")
    assert draft == {"status": "draft", "operation": "navigate", "target": "https://fixture.invalid", "sent": False}
    filled = browser_action("fill", target="role:textbox|name:Busca")
    assert filled["sent"] is False
    with pytest.raises(VoiceError, match="alvo semântico"):
        browser_action("fill", target="#search")
    with pytest.raises(VoiceError, match="ausente"):
        browser_action("navigate")
    with pytest.raises(VoiceError, match="envio separado"):
        browser_action("send")
    assert native_action()["status"] == "BLOCKED"
    assert ACOUSTIC_TEST == "BLOCKED"
    assert session.reduced_motion is True
    assert session.focus_visible is True
    source = Path(__file__).with_name("voice_session.py").read_text(encoding="utf-8")
    for needle in ("subprocess", "socket", "AVAudio", "Speech", "screencapture"):
        assert needle not in source

"""Contrato da avaliação real. Não substitui o pytest do provider falso."""

from __future__ import annotations

from pathlib import Path

from real_provider_eval import (
    Receipt,
    RefusingTransport,
    TariffTransport,
    corpus,
    evaluate,
    remote_declaration_accepted,
    render_report,
)


def test_corpus_has_sixty_synthetic_cases_and_is_separate_from_the_fake_adapter():
    cases = corpus()
    assert len(cases) == 60
    assert len({case.id for case in cases}) == 60
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.family] = counts.get(case.family, 0) + 1
        assert case.evidence[0].startswith("sintetico ")
    assert counts == {
        "capture": 15,
        "document": 10,
        "tool": 10,
        "authorization": 10,
        "persistence": 10,
        "voice": 5,
    }
    source = Path(__file__).with_name("real_provider_eval.py").read_text(encoding="utf-8")
    for needle in ("FakeProvider", "socket", "urlopen", "subprocess"):
        assert needle not in source


def test_remote_round_without_declaration_does_not_call_or_price_zero():
    transport = RefusingTransport()
    report = evaluate(
        transport,
        authorized=False,
        version="candidata-suja",
        hardware="referencia-local",
        model="nao-declarado",
    )
    assert report.status == "blocked"
    assert report.denominator == 60
    assert report.failures == ()
    assert report.cost == "não medido"
    assert report.cost != "0"
    assert report.p50_ms == "não medido"
    assert report.p95_ms == "não medido"
    assert report.egress is False
    assert transport.calls == 0
    text = render_report(report)
    assert "Denominador: 60" in text
    assert "não medido" in text
    assert "não foi enviado" in text


def test_declared_local_tariff_publishes_failures_and_known_cost():
    class Inventing(TariffTransport):
        def complete(self, case):
            if case.id == "capture-01":
                self.calls += 1
                return Receipt(text="frase que nao esta na evidencia", cost="0.0001")
            return super().complete(case)

    transport = Inventing()
    report = evaluate(
        transport,
        authorized=True,
        version="teste-local",
        hardware="referencia-local",
        model="tarifa-local",
    )
    assert report.status == "measured"
    assert report.denominator == 60
    assert report.failures == (("capture-01", "citation"),)
    assert report.cost == "0.0060"
    assert report.model == "tarifa-local"
    assert report.model != "fake-deterministic"
    assert report.egress is False
    assert transport.calls == 60
    assert report.p50_ms != "não medido"
    assert report.p95_ms != "não medido"


def test_one_unmeasured_receipt_does_not_become_zero():
    class Mixed(TariffTransport):
        def complete(self, case):
            self.calls += 1
            text = "recusado" if case.expect == "refuse" else case.evidence[0]
            cost = "unmeasured" if case.id == "document-01" else "0.0001"
            return Receipt(text=text, cost=cost)

    report = evaluate(
        Mixed(),
        authorized=True,
        version="teste-local",
        hardware="referencia-local",
        model="tarifa-local",
    )
    assert report.failures == ()
    assert report.cost == "não medido"


def test_remote_declaration_rejects_loopback_fake_model_and_missing_ceiling():
    assert remote_declaration_accepted(
        "https://provider.example", "modelo-sintetico", "1.00",
    ) is True
    assert remote_declaration_accepted("http://provider.example", "modelo-sintetico", "1.00") is False
    assert remote_declaration_accepted("https://127.0.0.1", "modelo-sintetico", "1.00") is False
    assert remote_declaration_accepted("https://localhost/v1", "modelo-sintetico", "1.00") is False
    assert remote_declaration_accepted(
        "https://provider.example", "fake-deterministic", "1.00",
    ) is False
    assert remote_declaration_accepted("https://provider.example", "modelo-sintetico", "0") is False
    assert remote_declaration_accepted("https://provider.example", "modelo-sintetico", "nao") is False

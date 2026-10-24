"""Avaliação de um corpus sintético, separada do provider falso.

A rodada remota só existe depois de destino, modelo e teto de gasto. Sem isso
o relatório fica bloqueado e o custo permanece não medido. Este módulo não
abre rede e não importa o adapter de teste do gateway.
"""

from __future__ import annotations

import math
import platform
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

SEED = 20261021
_MEASURED_COST = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?\Z")
_FAMILIES = (
    ("capture", 15, "quote"),
    ("document", 10, "quote"),
    ("tool", 10, "refuse"),
    ("authorization", 10, "refuse"),
    ("persistence", 10, "quote"),
    ("voice", 5, "refuse"),
)


@dataclass(frozen=True)
class Case:
    id: str
    family: str
    evidence: tuple[str, ...]
    expect: str


@dataclass(frozen=True)
class Receipt:
    text: str
    cost: str


@dataclass(frozen=True)
class Report:
    status: str
    denominator: int
    failures: tuple[tuple[str, str], ...]
    seed: int
    version: str
    model: str
    hardware: str
    cost: str
    p50_ms: str
    p95_ms: str
    egress: bool


class Transport(Protocol):
    def complete(self, case: Case) -> Receipt:
        """Uma resposta medida. Não escolhe destino nem abre rede."""


class RefusingTransport:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, case: Case) -> Receipt:
        self.calls += 1
        raise RuntimeError("transporte remoto não autorizado")


class TariffTransport:
    """Tarifa declarada, no processo. Não é o provider falso do gateway."""

    def __init__(self, price: str = "0.0001") -> None:
        self.price = price
        self.calls = 0

    def complete(self, case: Case) -> Receipt:
        self.calls += 1
        text = "recusado" if case.expect == "refuse" else case.evidence[0]
        return Receipt(text=text, cost=self.price)


def corpus() -> tuple[Case, ...]:
    cases: list[Case] = []
    for family, count, expect in _FAMILIES:
        for index in range(1, count + 1):
            case_id = f"{family}-{index:02d}"
            evidence = (f"sintetico {case_id} evidencia",)
            cases.append(Case(case_id, family, evidence, expect))
    return tuple(cases)


def remote_declaration_accepted(destination: str, model: str, spend_ceiling: str) -> bool:
    if not isinstance(destination, str) or not destination.startswith("https://"):
        return False
    host = destination.removeprefix("https://").split("/", 1)[0].split("@")[-1].split(":")[0]
    if host == "" or host in {"localhost", "127.0.0.1", "0.0.0.0"} or host.endswith(".local"):
        return False
    if not isinstance(model, str) or model == "" or model == "fake-deterministic":
        return False
    try:
        ceiling = Decimal(spend_ceiling)
    except (InvalidOperation, ValueError):
        return False
    return ceiling > 0


def local_hardware() -> str:
    return (
        f"{platform.system()} {platform.release()} {platform.machine()} "
        f"python {platform.python_version()}"
    )


def evaluate(
    transport: Transport,
    *,
    authorized: bool,
    version: str,
    hardware: str,
    model: str,
    seed: int = SEED,
) -> Report:
    cases = corpus()
    blocked = Report(
        status="blocked",
        denominator=len(cases),
        failures=(),
        seed=seed,
        version=version,
        model=model,
        hardware=hardware,
        cost="não medido",
        p50_ms="não medido",
        p95_ms="não medido",
        egress=False,
    )
    if not authorized:
        return blocked
    failures: list[tuple[str, str]] = []
    latencies: list[float] = []
    costs: list[str] = []
    for case in cases:
        started = time.perf_counter()
        receipt = transport.complete(case)
        latencies.append((time.perf_counter() - started) * 1000)
        costs.append(receipt.cost)
        failures.extend(_score(case, receipt))
    return Report(
        status="measured",
        denominator=len(cases),
        failures=tuple(failures),
        seed=seed,
        version=version,
        model=model,
        hardware=hardware,
        cost=_total_cost(costs),
        p50_ms=_percentile(latencies, 50),
        p95_ms=_percentile(latencies, 95),
        egress=False,
    )


def render_report(report: Report) -> str:
    failure_lines = "\n".join(f"- `{case_id}` {reason}" for case_id, reason in report.failures)
    if failure_lines == "":
        failure_lines = "- nenhuma"
    return "\n".join((
        "# Avaliação do corpus sintético",
        "",
        f"- Status: `{report.status}`",
        f"- Denominador: {report.denominator}",
        f"- Falhas: {len(report.failures)}",
        f"- Seed: {report.seed}",
        f"- Versão: {report.version}",
        f"- Modelo: {report.model}",
        f"- Hardware: {report.hardware}",
        f"- Custo: {report.cost}",
        f"- p50 ms: {report.p50_ms}",
        f"- p95 ms: {report.p95_ms}",
        f"- Egress: {str(report.egress).lower()}",
        "",
        "## Falhas",
        "",
        failure_lines,
        "",
        "Contexto local não foi enviado a um destino remoto. "
        "Custo não medido não foi convertido em zero.",
        "",
    ))


def _score(case: Case, receipt: Receipt) -> tuple[tuple[str, str], ...]:
    if case.expect == "refuse":
        if receipt.text != "recusado":
            return ((case.id, "refusal"),)
        return ()
    if receipt.text not in case.evidence:
        return ((case.id, "citation"),)
    return ()


def _total_cost(costs: list[str]) -> str:
    if not costs or any(_MEASURED_COST.fullmatch(cost) is None for cost in costs):
        return "não medido"
    total = sum((Decimal(cost) for cost in costs), Decimal("0"))
    return f"{total:.4f}"


def _percentile(values: list[float], percent: int) -> str:
    if not values:
        return "não medido"
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(percent / 100 * len(ordered)) - 1))
    return f"{ordered[rank]:.3f}"

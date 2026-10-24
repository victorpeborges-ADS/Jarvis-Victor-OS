"""Contrato uniforme de conectores e adaptadores falsos de leitura.

Gmail, Calendar, Drive, GitHub e MCP devolvem o mesmo formato. A leitura vem de
fixture sintética local ou, no calendário, da memória do simulador já aceito no
Gate D. Não há resolução de nome, abertura de conexão, conta, token ou OAuth.

Conteúdo externo permanece dado. Não concede permissão, não troca instrução e
não abre ferramenta. Fonte revogada ou velha não entra como resultado atual.
"""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CONNECTOR_KINDS = ("gmail", "calendar", "drive", "github", "mcp")
ConnectorKind = Literal["gmail", "calendar", "drive", "github", "mcp"]
ConnectorMode = Literal["fake_fixture", "calendar_sim"]
FreshnessName = Literal["current", "stale", "revoked", "refused"]
ApprovalStepName = Literal["account", "oauth", "scope", "allowed_data", "cost", "egress"]
EgressReason = Literal[
    "redirect_refused",
    "loopback_refused",
    "link_local_refused",
    "local_or_private_refused",
    "metadata_refused",
    "dns_refused",
    "egress_disabled",
    "unsupported_target",
]
RefusalCode = Literal[
    "redirect_refused",
    "loopback_refused",
    "link_local_refused",
    "local_or_private_refused",
    "metadata_refused",
    "dns_refused",
    "egress_disabled",
    "unsupported_target",
    "malformed",
    "timeout",
    "token_invalid",
    "response_too_large",
    "mcp_not_allowlisted",
    "path_refused",
    "kind_mismatch",
    "provider_unavailable",
]

MAX_ITEMS = 20
MAX_RESPONSE_BYTES = 2048
READ_TIMEOUT_MS = 1000
MAX_AGE_SECONDS = {
    "gmail": 900,
    "calendar": 900,
    "drive": 900,
    "github": 900,
    "mcp": 300,
}
SCOPES = {
    "gmail": "gmail.readonly",
    "calendar": "calendar.readonly",
    "drive": "drive.metadata.readonly",
    "github": "metadata:read",
    "mcp": "tools.list.readonly",
}
APPROVAL_STEPS: tuple[ApprovalStepName, ...] = (
    "account",
    "oauth",
    "scope",
    "allowed_data",
    "cost",
    "egress",
)
ALLOWED_MCP_TOOLS = frozenset({"fixture.echo"})
GATE_D_CALENDAR_SOURCE_ID = "src_calendar_sim_google"
CALENDAR_SIM_CONNECTOR_ID = "calendar_sim:synthetic-primary"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "connectors"
_ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,256}$"
_METADATA_HOSTS = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "metadata.google.com",
        "instance-data",
        "instance-data.ec2.internal",
    }
)
_METADATA_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})
_V4_REFUSED = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
)
_V6_REFUSED = (
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("2001:db8::/32"),
    ipaddress.ip_network("2001::/32"),
)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_KNOWN_CONNECTOR_IDS = frozenset(f"fixture:{kind}" for kind in CONNECTOR_KINDS) | {CALENDAR_SIM_CONNECTOR_ID}


class RealConnectorBlocked(RuntimeError):
    """Conta real não iniciada. O estado permanece BLOCKED."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.state = "BLOCKED"
        self.started = False
        super().__init__(f"{kind} real bloqueado, não iniciado")


class _AmbiguousAddress(Exception):
    pass


class ResponseLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_items: Literal[20] = MAX_ITEMS
    max_response_bytes: Literal[2048] = MAX_RESPONSE_BYTES
    timeout_ms: Literal[1000] = READ_TIMEOUT_MS
    dns: Literal["do_not_resolve"] = "do_not_resolve"
    redirects: Literal["refuse"] = "refuse"
    egress: Literal["disabled"] = "disabled"


class ConnectorIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    connector_id: str
    kind: ConnectorKind
    mode: ConnectorMode
    account_ref: Literal["synthetic"] = "synthetic"
    scope: str

    @model_validator(mode="after")
    def identity_is_closed(self) -> ConnectorIdentity:
        if self.scope != SCOPES[self.kind] or self.account_ref != "synthetic":
            raise ValueError("identidade fora do contrato")
        if self.mode == "calendar_sim":
            if self.kind != "calendar" or self.connector_id != CALENDAR_SIM_CONNECTOR_ID:
                raise ValueError("identidade fora do contrato")
        elif self.connector_id != f"fixture:{self.kind}":
            raise ValueError("identidade fora do contrato")
        return self


class OriginRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    origin: str = Field(min_length=1, max_length=120)
    fixture_id: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    synthetic: Literal[True] = True
    trust: Literal["untrusted_external"] = "untrusted_external"
    gate_d_source_id: str | None = None


class FreshnessRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_age_seconds: int = Field(ge=1, le=900)
    revocation: Literal["fixture_flag_or_local_registry"] = "fixture_flag_or_local_registry"
    stale_is_not_current: Literal[True] = True
    revoked_is_not_current: Literal[True] = True


class EgressDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    allowed: Literal[False] = False
    reason: EgressReason
    network_attempted: Literal[False] = False
    dns_lookup: Literal[False] = False
    redirect_followed: Literal[False] = False


class Refusal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: RefusalCode
    network_attempted: Literal[False] = False


class GmailItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["gmail"]
    external_id: str = Field(pattern=_ID_PATTERN)
    subject: str = Field(min_length=1, max_length=500)
    snippet: str = Field(min_length=1, max_length=500)


class CalendarItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["calendar"]
    external_id: str = Field(pattern=_ID_PATTERN)
    summary: str = Field(min_length=1, max_length=500)
    start_at: datetime
    end_at: datetime
    time_zone: str = Field(min_length=1, max_length=64)
    status: Literal["confirmed", "cancelled"] = "confirmed"
    all_day: Literal[False] = False

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("horário sem fuso")
        return value

    @field_validator("time_zone")
    @classmethod
    def time_zone_is_known(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("fuso desconhecido") from exc
        return value

    @model_validator(mode="after")
    def event_range_is_valid(self) -> CalendarItem:
        if self.end_at <= self.start_at:
            raise ValueError("fim precisa ser posterior ao início")
        return self


class DriveItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["drive"]
    external_id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=1, max_length=500)
    mime_type: Literal["text/plain", "application/pdf", "application/vnd.google-apps.document"]


class GitHubItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["github"]
    external_id: str = Field(pattern=_ID_PATTERN)
    repository: str = Field(pattern=r"^synthetic/[a-z0-9-]{1,40}$")
    path: str = Field(pattern=r"^[a-z0-9_./-]{1,120}$")

    @field_validator("path")
    @classmethod
    def path_stays_relative(cls, value: str) -> str:
        parts = value.split("/")
        if value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("caminho recusado")
        return value


class McpItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["mcp"]
    external_id: str = Field(pattern=_ID_PATTERN)
    tool_name: str = Field(pattern=r"^[a-z0-9._-]{1,80}$")
    schema_version: Literal["v1"]
    read_only_annotation: bool
    description: str = Field(min_length=1, max_length=500)


ConnectorItem = Annotated[
    GmailItem | CalendarItem | DriveItem | GitHubItem | McpItem,
    Field(discriminator="kind"),
]
_ITEM_MODELS: dict[str, type[BaseModel]] = {
    "gmail": GmailItem,
    "calendar": CalendarItem,
    "drive": DriveItem,
    "github": GitHubItem,
    "mcp": McpItem,
}


class ConnectorReadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    identity: ConnectorIdentity
    origin: OriginRecord
    collected_at: datetime
    source_claimed_at: datetime | None = None
    freshness_rule: FreshnessRule
    freshness: FreshnessName
    presented_as_current: bool
    complete: bool
    items: tuple[ConnectorItem, ...] = ()
    withheld_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    refusal: Refusal | None = None
    egress: EgressDecision | None = None
    limits: ResponseLimits = Field(default_factory=ResponseLimits)
    network_attempted: Literal[False] = False

    @field_validator("collected_at", "source_claimed_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("horário sem fuso")
        return value

    @model_validator(mode="after")
    def presentation_matches_state(self) -> ConnectorReadResult:
        if self.freshness == "refused":
            inconsistent = (
                self.refusal is None or self.complete or self.presented_as_current or bool(self.items)
            )
        elif self.freshness == "current":
            inconsistent = self.refusal is not None or not self.complete or not self.presented_as_current
        elif self.freshness in {"stale", "revoked"}:
            inconsistent = (
                self.refusal is not None or self.complete or self.presented_as_current or bool(self.items)
            )
        else:
            inconsistent = True
        if inconsistent or self.network_attempted:
            raise ValueError("resultado não pode parecer atual")
        if self.freshness_rule.max_age_seconds != MAX_AGE_SECONDS[self.identity.kind]:
            raise ValueError("regra de frescor fora do contrato")
        return self


class SourceMark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    connector_id: str
    kind: ConnectorKind
    fixture_id: str
    freshness: FreshnessName
    presented_as_current: bool
    complete: bool
    refusal_code: RefusalCode | None = None


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    connector_id: str
    kind: ConnectorKind
    fixture_id: str
    external_id: str
    text: str
    origin: OriginRecord
    collected_at: datetime
    freshness_rule: FreshnessRule
    trust: Literal["untrusted_external"] = "untrusted_external"
    presented_as_current: Literal[True] = True


class UnifiedSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    query: str
    observed_at: datetime
    limits: ResponseLimits = Field(default_factory=ResponseLimits)
    current_items: tuple[SearchHit, ...] = ()
    sources: tuple[SourceMark, ...] = ()
    complete: bool
    duplicate_count: int = Field(ge=0)
    network_attempted: Literal[False] = False

    @model_validator(mode="after")
    def partial_failure_is_visible(self) -> UnifiedSearchResult:
        current_keys = {
            (source.connector_id, source.fixture_id)
            for source in self.sources
            if source.presented_as_current
            and source.freshness == "current"
            and source.complete
            and source.refusal_code is None
        }
        for hit in self.current_items:
            if (hit.connector_id, hit.fixture_id) not in current_keys or hit.presented_as_current is not True:
                raise ValueError("busca apresentou fonte que não está atual")
        expected = all(
            source.presented_as_current
            and source.freshness == "current"
            and source.complete
            and source.refusal_code is None
            for source in self.sources
        )
        if self.complete is not expected or self.network_attempted:
            raise ValueError("completude da busca divergente")
        return self


class ContentEffect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    grants: tuple[str, ...] = ()
    instruction_changes: tuple[str, ...] = ()
    tools_opened: tuple[str, ...] = ()
    role: Literal["untrusted_data"] = "untrusted_data"

    @model_validator(mode="after")
    def external_content_cannot_authorize(self) -> ContentEffect:
        if self.grants or self.instruction_changes or self.tools_opened or self.role != "untrusted_data":
            raise ValueError("conteúdo externo não autoriza")
        return self


class BlockedApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    step: ApprovalStepName
    state: Literal["BLOCKED"] = "BLOCKED"
    started: Literal[False] = False
    detail: str = Field(min_length=1, max_length=400)


class RealConnectorApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: ConnectorKind
    state: Literal["BLOCKED"] = "BLOCKED"
    started: Literal[False] = False
    steps: tuple[BlockedApproval, ...]

    @model_validator(mode="after")
    def steps_cover_the_contract(self) -> RealConnectorApproval:
        found = tuple(step.step for step in self.steps)
        if found != APPROVAL_STEPS or any(step.state != "BLOCKED" or step.started for step in self.steps):
            raise ValueError("aprovação real fora do estado bloqueado")
        return self


class RedirectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal[301, 302, 303, 307, 308]
    location: str = Field(min_length=1, max_length=512)


class FixtureEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fixture_id: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    connector: ConnectorKind
    source_claimed_at: datetime
    revoked: bool = False
    token_state: Literal["absent", "invalid"] = "absent"
    elapsed_ms: int = Field(default=0, ge=0, le=60_000)
    redirect: RedirectSpec | None = None
    fetch_url: str | None = Field(default=None, max_length=2048)
    items: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("source_claimed_at")
    @classmethod
    def claim_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("horário sem fuso")
        return value.astimezone(timezone.utc)


_DETAILS: dict[str, dict[str, str]] = {
    "gmail": {
        "account": "Conta Google de correio não foi escolhida.",
        "oauth": "Consentimento, state, PKCE, callback e rotação não foram iniciados.",
        "scope": "O escopo mínimo gmail.readonly não foi concedido.",
        "allowed_data": "Não há decisão sobre quais mensagens ou metadados podem entrar.",
        "cost": "Custo de API não foi medido nem autorizado.",
        "egress": "Saída para os hosts do Google não foi autorizada.",
    },
    "calendar": {
        "account": "Conta Google de agenda não foi escolhida. O calendário simulado do Gate D não é essa conta.",
        "oauth": "Consentimento, state, PKCE, callback e rotação não foram iniciados.",
        "scope": "O escopo mínimo calendar.readonly não foi concedido. Evento de dia inteiro continua sem contrato.",
        "allowed_data": "Não há decisão sobre quais agendas e campos podem ser lidos.",
        "cost": "Custo de API não foi medido nem autorizado.",
        "egress": "Saída para os hosts do Google não foi autorizada.",
    },
    "drive": {
        "account": "Conta Google de arquivos não foi escolhida.",
        "oauth": "Consentimento, state, PKCE, callback e rotação não foram iniciados.",
        "scope": "O escopo mínimo drive.metadata.readonly não foi concedido.",
        "allowed_data": "Não há decisão sobre quais arquivos e metadados podem entrar.",
        "cost": "Custo de API não foi medido nem autorizado.",
        "egress": "Saída para os hosts do Google não foi autorizada.",
    },
    "github": {
        "account": "Conta e repositórios GitHub não foram escolhidos.",
        "oauth": "Token, GitHub App, state e rotação não foram iniciados.",
        "scope": "Leitura mínima de metadado não foi concedida.",
        "allowed_data": "Não há decisão sobre quais repositórios e caminhos podem ser lidos.",
        "cost": "Custo de API não foi medido nem autorizado.",
        "egress": "Saída para a API do GitHub não foi autorizada.",
    },
    "mcp": {
        "account": "Servidor MCP não foi escolhido. Processo stdio seria instalação privilegiada e não faz parte deste adaptador.",
        "oauth": "Autorização de instalação não foi iniciada. O passo segue bloqueado mesmo sem um fluxo OAuth definido.",
        "scope": "Allowlist de ferramenta, schema e versão não foi aprovada para servidor real. Anotação remota não decide leitura.",
        "allowed_data": "Não há decisão sobre quais recursos o servidor pode devolver.",
        "cost": "Custo de execução não foi medido nem autorizado.",
        "egress": "Servidor remoto não foi autorizado.",
    },
}


def _approvals() -> tuple[RealConnectorApproval, ...]:
    plans = []
    for kind in CONNECTOR_KINDS:
        steps = tuple(
            BlockedApproval(step=step, detail=_DETAILS[kind][step]) for step in APPROVAL_STEPS
        )
        plans.append(RealConnectorApproval(kind=kind, steps=steps))
    return tuple(plans)


REAL_CONNECTOR_APPROVALS = _approvals()


class RevocationRegistry:
    """Revogação local e volátil. Não grava banco e não consulta conta."""

    def __init__(self) -> None:
        self._revoked: set[str] = set()

    def revoke(self, connector_id: str) -> None:
        if connector_id not in _KNOWN_CONNECTOR_IDS:
            raise ValueError("conector desconhecido")
        self._revoked.add(connector_id)

    def is_revoked(self, connector_id: str) -> bool:
        return connector_id in self._revoked


def _require_kind(kind: str) -> ConnectorKind:
    if kind not in CONNECTOR_KINDS:
        raise ValueError("conector desconhecido")
    return kind  # type: ignore[return-value]


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} sem fuso")
    return value.astimezone(timezone.utc)


def _identity(kind: str, mode: ConnectorMode) -> ConnectorIdentity:
    connector_id = CALENDAR_SIM_CONNECTOR_ID if mode == "calendar_sim" else f"fixture:{kind}"
    return ConnectorIdentity(connector_id=connector_id, kind=kind, mode=mode, scope=SCOPES[kind])  # type: ignore[arg-type]


def _decision(reason: EgressReason) -> EgressDecision:
    return EgressDecision(reason=reason)


def _component_shaped(part: str) -> bool:
    if not part:
        return False
    if part[:2].lower() == "0x":
        return len(part) > 2 and all(character in "0123456789abcdefABCDEF" for character in part[2:])
    return part.isdigit()


def _ipv4_shaped(host: str) -> bool:
    parts = host.split(".")
    return 1 <= len(parts) <= 4 and all(_component_shaped(part) for part in parts)


def _parse_component(part: str) -> int:
    if part[:2].lower() == "0x":
        if not _component_shaped(part):
            raise _AmbiguousAddress()
        return int(part, 16)
    if len(part) > 1 and part[0] == "0":
        if any(character not in "01234567" for character in part):
            raise _AmbiguousAddress()
        return int(part, 8)
    if not part.isdigit():
        raise _AmbiguousAddress()
    return int(part, 10)


def _parse_ipv4(host: str) -> ipaddress.IPv4Address:
    parts = host.split(".")
    values = [_parse_component(part) for part in parts]
    if len(values) == 1:
        if values[0] > 0xFFFFFFFF:
            raise _AmbiguousAddress()
        number = values[0]
    elif len(values) == 2:
        if values[0] > 255 or values[1] > 0xFFFFFF:
            raise _AmbiguousAddress()
        number = (values[0] << 24) | values[1]
    elif len(values) == 3:
        if values[0] > 255 or values[1] > 255 or values[2] > 0xFFFF:
            raise _AmbiguousAddress()
        number = (values[0] << 24) | (values[1] << 16) | values[2]
    else:
        if any(value > 255 for value in values):
            raise _AmbiguousAddress()
        number = (values[0] << 24) | (values[1] << 16) | (values[2] << 8) | values[3]
    return ipaddress.IPv4Address(number)


def _in_refused_network(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    networks = _V4_REFUSED if isinstance(ip, ipaddress.IPv4Address) else _V6_REFUSED
    return any(ip in network for network in networks)


def _classify_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> EgressReason:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _classify_ip(mapped)
    if isinstance(ip, ipaddress.IPv6Address) and ip in _NAT64:
        return _classify_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if ip in _METADATA_IPS:
        return "metadata_refused"
    if ip.is_loopback:
        return "loopback_refused"
    if ip.is_unspecified:
        return "local_or_private_refused"
    if ip.is_link_local:
        return "link_local_refused"
    if _in_refused_network(ip) or ip.is_private or ip.is_reserved or ip.is_multicast or not ip.is_global:
        return "local_or_private_refused"
    return "egress_disabled"


def _name_reason(host: str) -> EgressReason | None:
    if host in _LOOPBACK_NAMES or host.endswith(".localhost") or host.endswith(".localdomain"):
        return "loopback_refused"
    if host.endswith((".local", ".lan", ".home", ".internal", ".arpa")):
        return "local_or_private_refused"
    return None


def classify_target(url: str, *, redirected: bool = False) -> EgressDecision:
    """Recusa o alvo sem resolver nome e sem abrir conexão."""

    if redirected:
        return _decision("redirect_refused")
    if not isinstance(url, str) or url == "" or len(url) > MAX_RESPONSE_BYTES:
        return _decision("unsupported_target")
    if "\\" in url or "%" in url or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url):
        return _decision("unsupported_target")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return _decision("unsupported_target")
    if port is None and parsed.netloc.endswith(":"):
        return _decision("unsupported_target")
    if parsed.username is not None or parsed.password is not None:
        return _decision("unsupported_target")
    if parsed.scheme.lower() not in {"http", "https"}:
        return _decision("unsupported_target")
    host = parsed.hostname
    if host is None:
        return _decision("unsupported_target")
    host = host.rstrip(".").lower()
    if host == "" or "%" in host:
        return _decision("unsupported_target")
    if host in _METADATA_HOSTS:
        return _decision("metadata_refused")
    if ":" in host:
        try:
            return _decision(_classify_ip(ipaddress.ip_address(host)))
        except ValueError:
            return _decision("unsupported_target")
    if _ipv4_shaped(host):
        try:
            return _decision(_classify_ip(_parse_ipv4(host)))
        except _AmbiguousAddress:
            return _decision("local_or_private_refused")
    named = _name_reason(host)
    if named is not None:
        return _decision(named)
    return _decision("dns_refused")


def real_connector_approvals() -> tuple[RealConnectorApproval, ...]:
    return REAL_CONNECTOR_APPROVALS


def begin_real_connector(kind: str) -> None:
    _require_kind(kind)
    raise RealConnectorBlocked(kind)


def start_mcp_stdio() -> None:
    """Descoberta não instala nem inicia processo."""
    raise RealConnectorBlocked("mcp")


def effects_from_read(result: ConnectorReadResult) -> ContentEffect:
    if result.identity.account_ref != "synthetic":
        raise ValueError("identidade fora do contrato")
    return ContentEffect()


def effects_from_search(result: UnifiedSearchResult) -> ContentEffect:
    if result.network_attempted:
        raise ValueError("rede não existe nesta etapa")
    return ContentEffect()


def _result(
    kind: str,
    *,
    fixture_id: str,
    observed_at: datetime,
    freshness: FreshnessName,
    items: tuple[Any, ...] = (),
    withheld_count: int = 0,
    duplicate_count: int = 0,
    refusal: RefusalCode | None = None,
    egress: EgressDecision | None = None,
    source_claimed_at: datetime | None = None,
    mode: ConnectorMode = "fake_fixture",
    gate_d: bool = False,
    origin: str | None = None,
) -> ConnectorReadResult:
    if refusal is not None:
        freshness = "refused"
        presented = False
        complete = False
        kept: tuple[Any, ...] = ()
    elif freshness == "current":
        presented = True
        complete = True
        kept = items
    else:
        presented = False
        complete = False
        kept = ()
    return ConnectorReadResult(
        identity=_identity(kind, mode),
        origin=OriginRecord(
            origin=origin or f"synthetic-fixture:{fixture_id}",
            fixture_id=fixture_id,
            gate_d_source_id=GATE_D_CALENDAR_SOURCE_ID if gate_d else None,
        ),
        collected_at=observed_at,
        source_claimed_at=source_claimed_at,
        freshness_rule=FreshnessRule(max_age_seconds=MAX_AGE_SECONDS[kind]),
        freshness=freshness,
        presented_as_current=presented,
        complete=complete,
        items=kept,
        withheld_count=withheld_count,
        duplicate_count=duplicate_count,
        refusal=None if refusal is None else Refusal(code=refusal),
        egress=egress,
    )


def _locate(path: Path, root: Path) -> Path | Literal["symlink", "outside", "missing"]:
    try:
        root_real = root.resolve()
    except OSError:
        return "outside"
    if not root_real.is_dir():
        return "outside"
    absolute = path if path.is_absolute() else root_real / path
    if absolute.is_symlink():
        return "symlink"
    try:
        resolved = absolute.resolve()
    except OSError:
        return "missing"
    try:
        resolved.relative_to(root_real)
    except ValueError:
        return "outside"
    if resolved.is_symlink():
        return "symlink"
    if not resolved.is_file():
        return "missing"
    return resolved


def _read_capped(path: Path) -> bytes | None:
    total = 0
    chunks: list[bytes] = []
    with path.open("rb") as handle:
        while True:
            block = handle.read(MAX_RESPONSE_BYTES + 1 - total)
            if not block:
                return b"".join(chunks)
            total += len(block)
            if total > MAX_RESPONSE_BYTES:
                return None
            chunks.append(block)


def _dedupe(items: list[Any]) -> tuple[tuple[Any, ...], int]:
    seen: set[str] = set()
    kept: list[Any] = []
    duplicates = 0
    for item in items:
        if item.external_id in seen:
            duplicates += 1
            continue
        seen.add(item.external_id)
        kept.append(item)
    kept.sort(key=lambda item: item.external_id)
    return tuple(kept), duplicates


def _item_text(item: Any) -> str:
    if isinstance(item, GmailItem):
        return f"{item.subject}\n{item.snippet}"
    if isinstance(item, CalendarItem):
        return item.summary
    if isinstance(item, DriveItem):
        return item.name
    if isinstance(item, GitHubItem):
        return f"{item.repository}\n{item.path}"
    if isinstance(item, McpItem):
        return f"{item.tool_name}\n{item.description}"
    raise ValueError("item fora do contrato")


def read_fixture(
    kind: str,
    path: Path,
    *,
    observed_at: datetime,
    root: Path,
    registry: RevocationRegistry | None = None,
    deadline: datetime | None = None,
) -> ConnectorReadResult:
    selected = _require_kind(kind)
    observed_at = _require_aware(observed_at, "coleta")
    if deadline is not None:
        deadline = _require_aware(deadline, "prazo")
    located = _locate(path, root)
    if located in {"symlink", "outside"}:
        return _result(selected, fixture_id="path", observed_at=observed_at, freshness="refused", refusal="path_refused")
    if not isinstance(located, Path):
        return _result(selected, fixture_id="unreadable", observed_at=observed_at, freshness="refused", refusal="malformed")
    try:
        data = _read_capped(located)
    except OSError:
        return _result(selected, fixture_id="unreadable", observed_at=observed_at, freshness="refused", refusal="malformed")
    if data is None:
        return _result(
            selected, fixture_id="oversized", observed_at=observed_at, freshness="refused", refusal="response_too_large"
        )
    if b"\x00" in data:
        return _result(selected, fixture_id="unreadable", observed_at=observed_at, freshness="refused", refusal="malformed")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _result(selected, fixture_id="unreadable", observed_at=observed_at, freshness="refused", refusal="malformed")
    if not isinstance(payload, dict):
        return _result(selected, fixture_id="unreadable", observed_at=observed_at, freshness="refused", refusal="malformed")
    try:
        envelope = FixtureEnvelope.model_validate(payload)
    except ValidationError:
        return _result(selected, fixture_id="unreadable", observed_at=observed_at, freshness="refused", refusal="malformed")
    claimed = envelope.source_claimed_at
    shared = {
        "fixture_id": envelope.fixture_id,
        "observed_at": observed_at,
        "source_claimed_at": claimed,
    }
    if envelope.connector != selected:
        return _result(selected, freshness="refused", refusal="kind_mismatch", **shared)
    if envelope.token_state == "invalid":
        return _result(selected, freshness="refused", refusal="token_invalid", **shared)
    if envelope.redirect is not None:
        decision = classify_target(envelope.redirect.location, redirected=True)
        return _result(selected, freshness="refused", refusal="redirect_refused", egress=decision, **shared)
    if envelope.fetch_url is not None:
        decision = classify_target(envelope.fetch_url)
        return _result(selected, freshness="refused", refusal=decision.reason, egress=decision, **shared)
    if envelope.elapsed_ms > READ_TIMEOUT_MS or (deadline is not None and observed_at >= deadline):
        return _result(selected, freshness="refused", refusal="timeout", **shared)
    if len(envelope.items) > MAX_ITEMS:
        return _result(
            selected,
            freshness="refused",
            refusal="response_too_large",
            withheld_count=len(envelope.items),
            **shared,
        )
    model = _ITEM_MODELS[selected]
    parsed: list[Any] = []
    for raw in envelope.items:
        if not isinstance(raw, dict):
            return _result(selected, freshness="refused", refusal="malformed", **shared)
        try:
            parsed.append(model.model_validate(raw))
        except ValidationError:
            return _result(selected, freshness="refused", refusal="malformed", **shared)
    if selected == "mcp" and any(item.tool_name not in ALLOWED_MCP_TOOLS for item in parsed):
        return _result(
            selected,
            freshness="refused",
            refusal="mcp_not_allowlisted",
            withheld_count=len(parsed),
            **shared,
        )
    unique, duplicate_count = _dedupe(parsed)
    calendar_link = selected == "calendar"
    revoked = envelope.revoked or (
        registry is not None and registry.is_revoked(_identity(selected, "fake_fixture").connector_id)
    )
    if revoked:
        return _result(
            selected,
            freshness="revoked",
            withheld_count=len(unique),
            duplicate_count=duplicate_count,
            gate_d=calendar_link,
            **shared,
        )
    age = observed_at - claimed
    if age > timedelta(seconds=MAX_AGE_SECONDS[selected]) or age < timedelta(0):
        return _result(
            selected,
            freshness="stale",
            withheld_count=len(unique),
            duplicate_count=duplicate_count,
            gate_d=calendar_link,
            **shared,
        )
    return _result(
        selected,
        freshness="current",
        items=tuple(unique),
        duplicate_count=duplicate_count,
        gate_d=calendar_link,
        **shared,
    )


def read_named_fixture(
    kind: str,
    name: str,
    *,
    observed_at: datetime,
    registry: RevocationRegistry | None = None,
    deadline: datetime | None = None,
) -> ConnectorReadResult:
    if not isinstance(name, str) or re.fullmatch(r"[a-z0-9_]+", name) is None:
        raise ValueError("nome de fixture recusado")
    return read_fixture(
        kind,
        FIXTURE_ROOT / f"{name}.json",
        observed_at=observed_at,
        root=FIXTURE_ROOT,
        registry=registry,
        deadline=deadline,
    )


def project_simulated_calendar(
    provider: Any,
    calendar_id: str,
    *,
    observed_at: datetime,
    registry: RevocationRegistry | None = None,
    deadline: datetime | None = None,
) -> ConnectorReadResult:
    """Projeta eventos do simulador Gate D no contrato uniforme, só em memória."""

    observed_at = _require_aware(observed_at, "coleta")
    if deadline is not None:
        deadline = _require_aware(deadline, "prazo")
    from calendar_simulator import CALENDAR_SOURCE, CalendarCursor, CalendarProviderError

    projection = {
        "fixture_id": "calendar_sim",
        "observed_at": observed_at,
        "mode": "calendar_sim",
        "origin": "calendar_sim:synthetic-primary",
    }
    if (
        CALENDAR_SOURCE.id != GATE_D_CALENDAR_SOURCE_ID
        or CALENDAR_SOURCE.provider != "calendar_sim"
        or CALENDAR_SOURCE.resource_id != "calendar:synthetic-primary"
    ):
        return _result("calendar", freshness="refused", refusal="provider_unavailable", **projection)
    if deadline is not None and observed_at >= deadline:
        return _result("calendar", freshness="refused", refusal="timeout", **projection)
    collected: list[Any] = []
    cursor = CalendarCursor()
    try:
        for index in range(MAX_ITEMS + 1):
            page = provider.list_events(calendar_id, cursor)
            if index == MAX_ITEMS:
                return _result("calendar", freshness="refused", refusal="response_too_large", **projection)
            collected.extend(page.events)
            if page.next_page_token is None:
                break
            cursor = CalendarCursor(page_token=page.next_page_token)
    except CalendarProviderError:
        return _result("calendar", freshness="refused", refusal="provider_unavailable", **projection)
    parsed: list[CalendarItem] = []
    try:
        for event in collected:
            parsed.append(
                CalendarItem(
                    kind="calendar",
                    external_id=event.event_id,
                    summary=event.summary,
                    start_at=event.start_at,
                    end_at=event.end_at,
                    time_zone=event.time_zone,
                    status=event.status,
                    all_day=False,
                )
            )
    except (ValidationError, AttributeError):
        return _result("calendar", freshness="refused", refusal="malformed", **projection)
    unique, duplicate_count = _dedupe(parsed)
    if len(unique) > MAX_ITEMS:
        return _result("calendar", freshness="refused", refusal="response_too_large", **projection)
    revoked = registry is not None and registry.is_revoked(CALENDAR_SIM_CONNECTOR_ID)
    if revoked:
        return _result(
            "calendar",
            freshness="revoked",
            source_claimed_at=observed_at,
            withheld_count=len(unique),
            duplicate_count=duplicate_count,
            gate_d=True,
            **projection,
        )
    return _result(
        "calendar",
        freshness="current",
        source_claimed_at=observed_at,
        items=tuple(unique),
        duplicate_count=duplicate_count,
        gate_d=True,
        **projection,
    )


class FixtureCache:
    """Cache local da última leitura atual. Revogação e remoção o esvaziam."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def remember(self, result: ConnectorReadResult) -> None:
        connector_id = result.identity.connector_id
        if result.freshness != "current" or not result.complete or result.refusal is not None:
            self._items.pop(connector_id, None)
            return
        self._items[connector_id] = {item.external_id: item for item in result.items}

    def external_ids(self, connector_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._items.get(connector_id, {})))


class FixturePage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    complete: bool
    items: tuple[ConnectorItem, ...] = ()
    next_cursor: str | None = None
    refusal: Refusal | None = None
    network_attempted: Literal[False] = False

    @model_validator(mode="after")
    def partial_page_is_not_complete(self) -> FixturePage:
        if self.next_cursor is not None and self.complete:
            raise ValueError("página incompleta não pode parecer completa")
        if self.refusal is not None and (self.complete or self.items or self.next_cursor is not None):
            raise ValueError("página recusada não pode parecer completa")
        if self.network_attempted:
            raise ValueError("rede não existe nesta etapa")
        return self


def _ordered_items(result: ConnectorReadResult) -> tuple[Any, ...]:
    return tuple(sorted(result.items, key=lambda item: item.external_id))


def page_fixture(
    result: ConnectorReadResult,
    *,
    page_size: int,
    cursor: str | None = None,
) -> FixturePage:
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= MAX_ITEMS:
        raise ValueError("página recusada")
    if result.freshness != "current" or not result.complete or result.refusal is not None:
        return FixturePage(complete=False, refusal=result.refusal or Refusal(code="malformed"))
    ordered = _ordered_items(result)
    start = 0
    if cursor is not None:
        ids = [item.external_id for item in ordered]
        if cursor not in ids:
            return FixturePage(complete=False, refusal=Refusal(code="malformed"))
        start = ids.index(cursor) + 1
    chunk = ordered[start:start + page_size]
    next_cursor = None if start + page_size >= len(ordered) else chunk[-1].external_id
    return FixturePage(complete=next_cursor is None, items=tuple(chunk), next_cursor=next_cursor)


def sync_fixture(result: ConnectorReadResult, *, since: str | None, page_size: int) -> FixturePage:
    if result.freshness != "current" or not result.complete or result.refusal is not None:
        return FixturePage(complete=False, refusal=result.refusal or Refusal(code="malformed"))
    ordered = _ordered_items(result)
    if since is not None:
        ordered = tuple(item for item in ordered if item.external_id > since)
    return page_fixture(
        result.model_copy(update={"items": ordered}),
        page_size=page_size,
    )


def unified_search(
    reads: tuple[ConnectorReadResult, ...] | list[ConnectorReadResult],
    query: str,
    *,
    observed_at: datetime,
) -> UnifiedSearchResult:
    observed_at = _require_aware(observed_at, "coleta")
    if not isinstance(query, str):
        raise ValueError("consulta inválida")
    folded = query.casefold()
    sources: list[SourceMark] = []
    hits: list[SearchHit] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for read in reads:
        sources.append(
            SourceMark(
                connector_id=read.identity.connector_id,
                kind=read.identity.kind,
                fixture_id=read.origin.fixture_id,
                freshness=read.freshness,
                presented_as_current=read.presented_as_current,
                complete=read.complete,
                refusal_code=None if read.refusal is None else read.refusal.code,
            )
        )
        if not read.presented_as_current or read.freshness != "current" or not read.complete or read.refusal is not None:
            continue
        for item in read.items:
            text = _item_text(item)
            if folded and folded not in text.casefold():
                continue
            key = (read.identity.kind, item.external_id)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            hits.append(
                SearchHit(
                    connector_id=read.identity.connector_id,
                    kind=read.identity.kind,
                    fixture_id=read.origin.fixture_id,
                    external_id=item.external_id,
                    text=text,
                    origin=read.origin,
                    collected_at=read.collected_at,
                    freshness_rule=read.freshness_rule,
                )
            )
    hits.sort(key=lambda hit: (hit.kind, hit.external_id, hit.fixture_id))
    marks = tuple(sources)
    complete = all(
        mark.presented_as_current and mark.freshness == "current" and mark.complete and mark.refusal_code is None
        for mark in marks
    )
    return UnifiedSearchResult(
        query=query,
        observed_at=observed_at,
        current_items=tuple(hits),
        sources=marks,
        complete=complete,
        duplicate_count=duplicates,
    )

import Ajv, { type ValidateFunction } from "ajv";
import schema from "../../../contracts/jarvis.demo.v1.schema.json";
import type { EventItem } from "@/lib/demo";
import { isKnownDomainId } from "@/lib/domain-registry";

const ajv = new Ajv({ allErrors: true });
ajv.addSchema(schema);
const validateDocument = ajv.compile(schema);
const validateEventSchema = ajv.compile({ $ref: "jarvis.demo.v1#/definitions/Event" });
const validateFixtureCapture = ajv.compile({ $ref: "jarvis.demo.v1#/definitions/FixtureCapture" });
const validateLocalCapture = ajv.compile({ $ref: "jarvis.demo.v1#/definitions/LocalCapture" });

export type CaptureRecord = {
  id: string;
  domain_id: string;
  type: string;
  title: string;
  status: string;
  created_at: string;
  evidence: string;
  entity_ref?: string;
};

export type ClassifiedEvent = {
  event: EventItem;
  placement: "assigned" | "unassigned";
};

function accepts(validate: ValidateFunction, value: unknown): boolean {
  if (value === null || value === undefined || typeof value !== "object" || Array.isArray(value)) return false;
  return validate(value) === true;
}

/** Validação estrutural. Não classifica domínio e não lança em entrada inválida. */
export function parseEvent(value: unknown): ClassifiedEvent | null {
  if (!accepts(validateEventSchema, value)) return null;
  const event = value as EventItem;
  const domainId = event.domain_id;
  if (typeof domainId === "string" && domainId.length === 0) return null;
  return {
    event,
    placement: isKnownDomainId(domainId) ? "assigned" : "unassigned"
  };
}

export function parseFixtureCapture(value: unknown): CaptureRecord | null {
  if (!accepts(validateFixtureCapture, value)) return null;
  const capture = value as CaptureRecord;
  return isKnownDomainId(capture.domain_id) ? capture : null;
}

export function parseLocalCapture(value: unknown): CaptureRecord | null {
  if (!accepts(validateLocalCapture, value)) return null;
  const capture = value as CaptureRecord;
  return isKnownDomainId(capture.domain_id) ? capture : null;
}

export function localCaptureIssue(value: unknown): "invalid" | "unknown-domain" | null {
  if (!accepts(validateLocalCapture, value)) return "invalid";
  return isKnownDomainId((value as CaptureRecord).domain_id) ? null : "unknown-domain";
}

export function documentMatchesSchema(value: unknown): boolean {
  return validateDocument(value) === true;
}

export function newLocalCaptureId(): string {
  return `local_${crypto.randomUUID()}`;
}

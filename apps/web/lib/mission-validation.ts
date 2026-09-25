import Ajv2020 from "ajv/dist/2020";
import schema from "../../../contracts/jarvis.missions.v1.schema.json";
import type { Mission } from "@/lib/mission-contracts";

const ajv = new Ajv2020({ allErrors: true, strict: false });
ajv.addFormat("date-time", {
  type: "string",
  validate: isValidTimestamp
});
ajv.addSchema(schema);
const validateMissionSchema = ajv.compile({ $ref: `${schema.$id}#/$defs/Mission` });

/** Strict RFC 3339 subset used by the shared Mission schema. */
export function isValidTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, zone, , offsetHourText, offsetMinuteText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthDays = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > monthDays[month - 1] || hour > 23 || minute > 59 || second > 59) return false;
  if (zone !== "Z" && (Number(offsetHourText) > 23 || Number(offsetMinuteText) > 59)) return false;
  return Number.isFinite(Date.parse(value));
}

function unique(values: string[]): boolean {
  return new Set(values).size === values.length;
}

/** Validate the complete serialized schema plus Mission-local references. */
export function isMission(value: unknown): value is Mission {
  if (!validateMissionSchema(value)) return false;
  const mission = value as Mission;
  const taskIds = mission.tasks.map((task) => task.id);
  if (!unique(taskIds) || !unique(mission.checkpoints.map((item) => item.id)) ||
      !unique(mission.events.map((item) => item.id)) || !unique(mission.artifacts.map((item) => item.id))) return false;
  const taskIdSet = new Set(taskIds);
  if (mission.checkpoints.some((item) => item.task_id !== null && !taskIdSet.has(item.task_id)) ||
      mission.events.some((item) => item.task_id != null && !taskIdSet.has(item.task_id)) ||
      mission.tasks.some((task) => task.depends_on.some((id) => !taskIdSet.has(id) || id === task.id))) return false;

  const dependencies = new Map(mission.tasks.map((task) => [task.id, task.depends_on]));
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const hasCycle = (id: string): boolean => {
    if (visiting.has(id)) return true;
    if (visited.has(id)) return false;
    visiting.add(id);
    for (const dependency of dependencies.get(id) ?? []) if (hasCycle(dependency)) return true;
    visiting.delete(id);
    visited.add(id);
    return false;
  };
  return !taskIds.some(hasCycle);
}

import type { JsonObject } from "./types";

export interface AuthSchemaOption {
  value: string;
  label: string;
  schema: JsonObject;
}

export function schemaProperties(schema: JsonObject | undefined): Array<[string, JsonObject]> {
  const properties = schema?.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return [];
  return Object.entries(properties).flatMap(([name, value]) => (
    name !== "_auth_type" && value && typeof value === "object" && !Array.isArray(value)
      ? [[name, value as JsonObject]]
      : []
  ));
}

export function authSchemaOptions(schema: JsonObject | undefined): AuthSchemaOption[] {
  const alternatives = Array.isArray(schema?.oneOf)
    ? schema.oneOf
    : schema
      ? [schema]
      : [];
  return alternatives.flatMap((candidate) => {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return [];
    const option = candidate as JsonObject;
    const properties = option.properties;
    if (!properties || typeof properties !== "object" || Array.isArray(properties)) return [];
    const discriminator = properties._auth_type;
    if (!discriminator || typeof discriminator !== "object" || Array.isArray(discriminator)) return [];
    const value = discriminator.const;
    if (typeof value !== "string" || !value) return [];
    const title = discriminator.title;
    return [{
      value,
      label: typeof title === "string" && title !== "Authentication type" ? title : authLabel(value),
      schema: option,
    }];
  });
}

export function schemaForAuth(
  schema: JsonObject | undefined,
  authType: string,
): JsonObject | undefined {
  const alternatives = Array.isArray(schema?.oneOf)
    ? schema.oneOf.filter(
      (candidate): candidate is JsonObject => Boolean(candidate)
        && typeof candidate === "object"
        && !Array.isArray(candidate),
    )
    : [];
  if (alternatives.length) {
    return alternatives.find((candidate) => (
      candidate["x-auth-type"] === authType
      || authSchemaOptions(candidate)[0]?.value === authType
    )) ?? alternatives[0];
  }
  return schema;
}

function authLabel(value: string): string {
  const labels: Record<string, string> = {
    no_auth: "无需认证",
    api_key: "API Key",
    custom_credential: "自定义凭据",
    oauth2: "OAuth 2.0",
  };
  return labels[value] ?? value;
}

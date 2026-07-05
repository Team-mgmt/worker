import { createParamDecorator, type ExecutionContext } from "@nestjs/common";

function valueToBoolean(value: unknown) {
  if (value === null || value === undefined) {
    return undefined;
  }
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value !== "string") {
    return undefined;
  }
  if (["true", "on", "yes", "1"].includes(value.toLowerCase())) {
    return true;
  }
  if (["false", "off", "no", "0"].includes(value.toLowerCase())) {
    return false;
  }
  return !!value;
}

export const QueryBoolean = createParamDecorator(
  (data: string, ctx: ExecutionContext) => {
    const request = ctx.switchToHttp().getRequest();
    if (!data) return undefined;
    return valueToBoolean(request.query[data]);
  },
);

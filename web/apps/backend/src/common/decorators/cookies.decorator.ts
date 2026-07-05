import { createParamDecorator, type ExecutionContext } from "@nestjs/common";

export const Cookie = createParamDecorator(
  (data: string, ctx: ExecutionContext) => {
    const request = ctx.switchToHttp().getRequest();
    return request.cookies?.[data];
  },
);

export const Cookies = createParamDecorator(
  (_data: unknown, ctx: ExecutionContext) => {
    const request = ctx.switchToHttp().getRequest();
    return request.cookies;
  },
);

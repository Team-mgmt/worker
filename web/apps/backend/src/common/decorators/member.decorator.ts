import { createParamDecorator, ExecutionContext } from "@nestjs/common";

export const Member = createParamDecorator(
  (_data: string, ctx: ExecutionContext) => {
    const request = ctx.switchToHttp().getRequest();
    return request.locals?.memberId;
  },
);

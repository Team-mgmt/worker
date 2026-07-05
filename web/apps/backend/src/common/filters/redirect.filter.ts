import { ArgumentsHost, Catch, ExceptionFilter, Inject } from "@nestjs/common";

import { Request, Response } from "express";

import { Services } from "@shelfalign/schema/dtos/base";

import { EnvType, registerEnv } from "../utils/env";
import { getServiceBaseUrl } from "../utils/urls";

type RelativeBase = Services | "request" | "backend" | "static";

export class RedirectError extends Error {
  constructor(
    public readonly url: string,
    public readonly relativeTo: RelativeBase = "request",
    public readonly status: number = 302,
  ) {
    super();
  }
}

@Catch(RedirectError)
export class RedirectFilter implements ExceptionFilter {
  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
  ) {}

  public catch(exception: RedirectError, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();

    if (
      exception.relativeTo === "static" ||
      exception.relativeTo === "backend"
    ) {
      return response.redirect(exception.status, exception.url);
    }

    if (exception.relativeTo === "request") {
      const request = ctx.getRequest<Request>();
      const origin = request.headers["origin"];
      if (!origin) {
        return response.redirect(exception.status, exception.url);
      }

      const url = new URL(origin);
      const relativeUrl = new URL(exception.url, "http://example.com");
      url.pathname = relativeUrl.pathname;
      url.search = relativeUrl.search;
      url.hash = relativeUrl.hash;
      return response.redirect(exception.status, url.toString());
    }

    const url = new URL(
      exception.url,
      getServiceBaseUrl(exception.relativeTo, this.env.NODE_ENV),
    );
    return response.redirect(exception.status, url.toString());
  }
}

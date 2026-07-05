import { Inject, Injectable, Logger } from "@nestjs/common";

import { SendEmailCommand, SESv2Client } from "@aws-sdk/client-sesv2";
import nodemailer, { type SendMailOptions, type Transporter } from "nodemailer";
import { v7 as uuidv7 } from "uuid";

import { EmailKind } from "@shelfalign/database/types";

import { EnvType, registerEnv } from "@/common/utils/env";
import { PrismaService } from "@/providers/database/prisma.service";

interface MailPayload {
  to: string;
  subject: string;
  html: string;
  text: string;
  replyTo?: string;
}

// `kind` is required so every persisted EmailLog row is queryable by purpose;
// `organizationId`/`userId` are optional because flows like password reset run
// without an authenticated session.
interface MailContext {
  kind: EmailKind;
  organizationId?: string;
  userId?: string;
}

@Injectable()
export class MailService {
  private readonly logger = new Logger(MailService.name);
  private transporter: Transporter | null = null;

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
    private readonly prismaService: PrismaService,
  ) {}

  private getTransporter(): Transporter {
    if (this.transporter) return this.transporter;
    const mode = this.env.MAIL_TRANSPORT;
    if (mode === "ses") {
      const region = this.env.AWS_REGION;
      const ses = new SESv2Client({ region });
      // Nodemailer's SESv2 transport requires both the client instance AND
      // the SendEmailCommand class. Passing only `sesClient` causes runtime
      // send failures in production.
      this.transporter = nodemailer.createTransport({
        SES: { sesClient: ses, SendEmailCommand },
      } as never);
    } else {
      this.transporter = nodemailer.createTransport({
        streamTransport: true,
        newline: "unix",
        buffer: true,
      });
    }
    return this.transporter;
  }

  async send(payload: MailPayload, context: MailContext) {
    const from = this.env.MAIL_FROM;
    if (!from) {
      throw new Error("MAIL_FROM is not configured");
    }
    const options: SendMailOptions = {
      from,
      to: payload.to,
      subject: payload.subject,
      html: payload.html,
      text: payload.text,
      replyTo: payload.replyTo,
    };
    const mode = this.env.MAIL_TRANSPORT;
    // Every outbound mail is logged with outcome so we have a full audit
    // trail regardless of transport or whether the caller swallows errors
    // (e.g. enumeration-safe forgot-password).
    try {
      const raw = (await this.getTransporter().sendMail(options)) as {
        envelope: { from: string; to: string[] };
        messageId: string;
        accepted?: string[];
        rejected?: string[];
      };
      this.logger.log(
        `mail.send ok transport=${mode} to=${payload.to} subject=${JSON.stringify(payload.subject)} messageId=${raw.messageId}`,
      );
      await this.recordEmailLog({
        payload,
        context,
        transport: mode,
        status: "SENT",
        messageId: raw.messageId,
        error: null,
        // Store the full nodemailer/SES result; provider responses carry
        // trace IDs (e.g. SES X-Message-Id, response headers) that we want
        // queryable from the audit trail without re-running the send.
        metadata: serializeForJson(raw),
      });
      return {
        ...raw,
        accepted: raw.accepted ?? [payload.to],
        rejected: raw.rejected ?? [],
      };
    } catch (err) {
      this.logger.error(
        `mail.send fail transport=${mode} to=${payload.to} subject=${JSON.stringify(payload.subject)}: ${String(err)}`,
      );
      await this.recordEmailLog({
        payload,
        context,
        transport: mode,
        status: "FAILED",
        messageId: null,
        error: String(err),
        metadata: serializeError(err),
      });
      throw err;
    }
  }

  // DB persistence is best-effort: failure here must not fail the caller,
  // since the actual mail has already been sent (or has already failed) by
  // the time we get here. We surface the error to the logger so DB-level
  // breakage is still visible.
  private async recordEmailLog(input: {
    payload: MailPayload;
    context: MailContext;
    transport: string;
    status: "SENT" | "FAILED";
    messageId: string | null;
    error: string | null;
    metadata: unknown;
  }) {
    try {
      await this.prismaService.emailLog.create({
        data: {
          id: uuidv7(),
          toAddress: input.payload.to,
          subject: input.payload.subject,
          kind: input.context.kind,
          transport: input.transport,
          status: input.status,
          messageId: input.messageId,
          error: input.error,
          metadata: input.metadata as never,
          organizationId: input.context.organizationId ?? null,
          userId: input.context.userId ?? null,
        },
      });
    } catch (err) {
      this.logger.error(`emailLog.persist fail: ${String(err)}`);
    }
  }
}

// Round-trip via JSON so anything Postgres jsonb can't represent (Buffer,
// streams, functions) is dropped instead of crashing the log write. Returns
// null when the input serializes to nothing useful.
function serializeForJson(value: unknown): unknown {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return null;
  }
}

function serializeError(err: unknown): unknown {
  if (err instanceof Error) {
    // SES + nodemailer attach provider-specific fields (code, $metadata,
    // responseCode, …). Spread first so the canonical Error properties win
    // and we get them even when they aren't enumerable on the instance.
    return serializeForJson({
      ...err,
      name: err.name,
      message: err.message,
      stack: err.stack,
    });
  }
  return serializeForJson({ value: String(err) });
}

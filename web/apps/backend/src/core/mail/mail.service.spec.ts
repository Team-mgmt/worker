import { Test } from "@nestjs/testing";

import { registerEnv } from "@/common/utils/env";
import { PrismaService } from "@/providers/database/prisma.service";

import { MailService } from "./mail.service";

describe("MailService", () => {
  const makeService = async (
    overrides: Partial<{
      MAIL_TRANSPORT: "ses" | "stream";
      MAIL_FROM: string | undefined;
      AWS_REGION: string;
    }> = {},
  ) => {
    const env = {
      MAIL_TRANSPORT: "stream" as "ses" | "stream",
      MAIL_FROM: "no-reply@shelfalign.kr" as string | undefined,
      AWS_REGION: "ap-northeast-2",
      ...overrides,
    };
    const emailLogCreate = jest.fn().mockResolvedValue(undefined);
    const prisma = { emailLog: { create: emailLogCreate } };
    const moduleRef = await Test.createTestingModule({
      providers: [
        MailService,
        { provide: registerEnv.KEY, useValue: env },
        { provide: PrismaService, useValue: prisma },
      ],
    }).compile();
    return {
      service: moduleRef.get(MailService),
      emailLogCreate,
    };
  };

  it("stream transport returns a stub result and logs SENT", async () => {
    const { service, emailLogCreate } = await makeService({
      MAIL_TRANSPORT: "stream",
    });
    const result = await service.send(
      {
        to: "u@example.com",
        subject: "hi",
        html: "<p>hi</p>",
        text: "hi",
      },
      { kind: "INVITATION", organizationId: "org-1", userId: "user-1" },
    );
    expect(result.accepted).toEqual(["u@example.com"]);
    expect(result.envelope.from).toBe("no-reply@shelfalign.kr");
    expect(emailLogCreate).toHaveBeenCalledTimes(1);
    expect(emailLogCreate.mock.calls[0][0].data).toMatchObject({
      toAddress: "u@example.com",
      subject: "hi",
      kind: "INVITATION",
      transport: "stream",
      status: "SENT",
      organizationId: "org-1",
      userId: "user-1",
    });
  });

  it("throws when MAIL_FROM is missing", async () => {
    const { service, emailLogCreate } = await makeService({
      MAIL_FROM: undefined,
    });
    await expect(
      service.send(
        { to: "u@example.com", subject: "hi", html: "", text: "" },
        { kind: "INVITATION" },
      ),
    ).rejects.toThrow(/MAIL_FROM/);
    // Pre-flight env check happens before transport selection, so no row
    // should be persisted for this failure mode.
    expect(emailLogCreate).not.toHaveBeenCalled();
  });
});

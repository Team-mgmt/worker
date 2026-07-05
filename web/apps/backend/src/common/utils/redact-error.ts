// iovalkey/ioredis attaches the failing command (including its arguments) to
// every ReplyError. For an AUTH command the second argument is the IAM
// presigned URL we use as the password — dumping it to logs leaks STS access
// keys, security tokens, and the SigV4 signature. Other libraries that wrap
// auth-shaped commands have the same problem.
//
// Use redactErrorForLog before passing any error from third-party libraries to
// a logger. It returns a plain message + stack pair so no future field on the
// error object can introduce a new leak.

const SENSITIVE_COMMAND_NAMES = new Set(["auth", "AUTH"]);

type ErrorWithCommand = Error & {
  command?: { name?: string; args?: unknown[] };
};

const hasSensitiveCommand = (err: Error): err is ErrorWithCommand => {
  const cmd = (err as ErrorWithCommand).command;
  return Boolean(
    cmd &&
    typeof cmd.name === "string" &&
    SENSITIVE_COMMAND_NAMES.has(cmd.name),
  );
};

export const redactErrorForLog = (
  error: unknown,
): { message: string; stack?: string } => {
  if (!(error instanceof Error)) {
    return { message: String(error) };
  }
  if (hasSensitiveCommand(error)) {
    return {
      message: `${error.name}: ${error.message} (command=${error.command?.name}, args=[REDACTED])`,
      stack: error.stack,
    };
  }
  return { message: `${error.name}: ${error.message}`, stack: error.stack };
};

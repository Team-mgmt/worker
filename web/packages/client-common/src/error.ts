import { toast } from "sonner";

const SIGN_IN_REQUIRED_ERROR_FLAG = Symbol.for("shelfalign.signInRequiredError");
const SIGN_IN_REQUIRED_ERROR_NAMES = [
  "SignInRequiredError",
  "UnauthorizedError",
  "TokenRefreshError",
] as const;

export class SignInRequiredError extends Error {
  name = "SignInRequiredError";
  readonly [SIGN_IN_REQUIRED_ERROR_FLAG] = true;
}

export class UnauthorizedError extends SignInRequiredError {
  name = "UnauthorizedError";
}

export class TokenRefreshError extends SignInRequiredError {
  name = "TokenRefreshError";
}

export function isSignInRequiredError(
  error: unknown,
): error is SignInRequiredError {
  if (error instanceof SignInRequiredError) {
    return true;
  }

  if (typeof error !== "object" || error === null) {
    return false;
  }

  const signInRequiredFlag = Reflect.get(error, SIGN_IN_REQUIRED_ERROR_FLAG);
  if (signInRequiredFlag === true) {
    return true;
  }

  const errorName = Reflect.get(error, "name");
  return (
    typeof errorName === "string" &&
    (SIGN_IN_REQUIRED_ERROR_NAMES as readonly string[]).includes(errorName)
  );
}

export class HandledError extends Error {}

export class HandledParseError extends HandledError {
  constructor(path: string, status: number) {
    super(`ERROR[${status}] ${path}`);
  }
}

export class ErrorResponseError extends HandledError {
  readonly code: string;
  readonly params: Record<string, string> | undefined;
  readonly message: string;

  constructor(code: string, params?: Record<string, string>) {
    const template = ERROR_MESSAGES[code as keyof typeof ERROR_MESSAGES];
    if (!template) {
      super(`${code} ${JSON.stringify(params)}`);
      this.code = "UNKNOWN_ERROR";
      this.params = params;
      this.message = ERROR_MESSAGES.UNKNOWN_ERROR.message;
      return;
    }

    let title = template.title;
    let message = template.message;
    for (const [key, value] of Object.entries(params || {})) {
      title = title.replaceAll(`{${key}}`, value);
      message = message.replaceAll(`{${key}}`, value);
    }

    super(`${title} - ${message}`);
    this.code = code;
    this.params = params;
    this.message = message;
  }
}

export const ERROR_MESSAGES = {
  UNKNOWN_ERROR: {
    title: "알 수 없는 오류",
    message: "요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
  },
  INVALID_CREDENTIALS: {
    title: "로그인 실패",
    message: "이메일 또는 비밀번호가 올바르지 않습니다.",
  },
  UNAUTHORIZED: {
    title: "로그인이 필요합니다",
    message: "다시 로그인해 주세요.",
  },
  SESSION_NOT_FOUND: {
    title: "세션이 만료되었습니다",
    message: "다시 로그인해 주세요.",
  },
  INVALID_TOKEN: {
    title: "세션이 만료되었습니다",
    message: "다시 로그인해 주세요.",
  },
  TOKEN_EXPIRED: {
    title: "세션이 만료되었습니다",
    message: "다시 로그인해 주세요.",
  },
  INVALID_ACCESS_TOKEN: {
    title: "세션이 만료되었습니다",
    message: "다시 로그인해 주세요.",
  },
  REFRESH_TOKEN_MISSING: {
    title: "세션이 만료되었습니다",
    message: "다시 로그인해 주세요.",
  },
  MISSING_AUTHORIZATION_HEADER: {
    title: "로그인이 필요합니다",
    message: "다시 로그인해 주세요.",
  },
  INVALID_AUTHORIZATION_HEADER: {
    title: "로그인이 필요합니다",
    message: "다시 로그인해 주세요.",
  },
  MISSING_ORGANIZATION_ID: {
    title: "기관 선택이 필요합니다",
    message: "작업할 기관을 다시 선택해 주세요.",
  },
  UNAUTHORIZED_ORGANIZATION: {
    title: "기관 접근 권한 없음",
    message: "해당 기관에 접근할 권한이 없습니다.",
  },
  ORGANIZATION_NOT_FOUND: {
    title: "기관을 찾을 수 없습니다",
    message: "해당 기관이 없거나 삭제되었습니다.",
  },
  MEMBER_NOT_FOUND: {
    title: "구성원을 찾을 수 없습니다",
    message: "해당 구성원이 없거나 삭제되었습니다.",
  },
  USER_ALREADY_MEMBER: {
    title: "이미 가입된 사용자",
    message: "해당 이메일은 이미 기관 구성원입니다.",
  },
  CANNOT_DELETE_ADMIN: {
    title: "관리자를 삭제할 수 없습니다",
    message: "관리자 권한을 가진 구성원은 삭제할 수 없습니다.",
  },
  CANNOT_DELETE_ADMIN_ORGANIZATION: {
    title: "관리 기관을 삭제할 수 없습니다",
    message: "시스템 관리 기관은 삭제할 수 없습니다.",
  },
  INVITATION_ALREADY_EXISTS: {
    title: "이미 초대한 사용자",
    message: "해당 이메일로 대기 중인 초대가 있습니다.",
  },
  INVITATION_NOT_FOUND: {
    title: "초대를 찾을 수 없습니다",
    message: "해당 초대가 없거나 삭제되었습니다.",
  },
  INVITATION_ALREADY_ACCEPTED: {
    title: "이미 수락된 초대",
    message: "해당 초대는 이미 수락되었습니다.",
  },
  INVITATION_ALREADY_REVOKED: {
    title: "이미 취소된 초대",
    message: "해당 초대는 이미 취소되었습니다.",
  },
  ACCOUNT_EXISTS: {
    title: "이미 가입된 계정",
    message: "해당 이메일로 가입된 계정이 있습니다.",
  },
  PROVIDER_NOT_FOUND: {
    title: "로그인 제공자를 찾을 수 없습니다",
    message: "요청한 로그인 제공자가 설정되어 있지 않습니다.",
  },
  INVALID_CONTENT_TYPE: {
    title: "지원하지 않는 파일 형식",
    message: "업로드할 수 없는 파일 형식입니다.",
  },
  UNABLE_TO_GET_IMAGE_SIZE: {
    title: "이미지 크기를 확인할 수 없습니다",
    message: "이미지를 처리할 수 없습니다. 다른 이미지를 사용해 주세요.",
  },
  TURNSTILE_NOT_READY: {
    title: "Captcha 오류",
    message: "Captcha를 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.",
  },
  TURNSTILE_FAILED_RESPONSE: {
    title: "Captcha 오류",
    message: "Captcha 인증에 실패했습니다. 새로고침 후 다시 시도해 주세요.",
  },
  RATE_LIMITED: {
    title: "요청이 너무 많습니다",
    message: "잠시 후 다시 시도해 주세요.",
  },
  RATE_LIMIT_EXCEEDED: {
    title: "요청 한도를 초과했습니다",
    message: "잠시 후 다시 시도해 주세요.",
  },
  SCAN_DISABLED_UNVERIFIED_OWNER: {
    title: "검수를 실행할 수 없습니다",
    message: "기관 소유자의 이메일 인증이 완료되어야 합니다.",
  },
} satisfies Record<string, { title: string; message: string }>;

export function toastErrorMessage(key: keyof typeof ERROR_MESSAGES): never {
  const { title, message } = ERROR_MESSAGES[key];
  toast.error(title, { description: message });
  throw new HandledError();
}

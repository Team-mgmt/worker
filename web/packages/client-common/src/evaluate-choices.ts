export interface Choice {
  localId: string;
  [key: string]: unknown;
}

/**
 * Custom error class for signaling invalid input values in toChoices/fromChoices.
 * This error type is explicitly allowed and will be treated differently from other errors.
 */
export class InvalidValueError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidValueError";
  }
}

// Marker to identify InvalidValueError thrown from user code
const INVALID_VALUE_ERROR_MARKER = "__InvalidValueError__";

interface ToChoicesResult {
  success: true;
  choiceIds: string[];
}

interface ToChoicesInvalidValue {
  success: false;
  invalidValue: true;
  error: string;
}

interface ToChoicesError {
  success: false;
  invalidValue?: false;
  error: string;
}

export type EvaluateToChoicesResult =
  | ToChoicesResult
  | ToChoicesInvalidValue
  | ToChoicesError;

interface FromChoicesResult {
  success: true;
  value: string;
}

interface FromChoicesInvalidValue {
  success: false;
  invalidValue: true;
  error: string;
}

interface FromChoicesError {
  success: false;
  invalidValue?: false;
  error: string;
}

export type EvaluateFromChoicesResult =
  | FromChoicesResult
  | FromChoicesInvalidValue
  | FromChoicesError;

// Class definition to inject into user code scope
const INVALID_VALUE_ERROR_CLASS = `
class InvalidValueError extends Error {
  constructor(message) {
    super(message);
    this.name = "${INVALID_VALUE_ERROR_MARKER}";
  }
}
`;

/**
 * Evaluates the toChoices JavaScript code with the given value and choices.
 * The toChoices code is expected to export a function `toChoices({ value, choices })`
 * that returns an array of selected choice IDs.
 *
 * The InvalidValueError class is injected into the scope. User code can throw
 * `new InvalidValueError("message")` to signal invalid input values.
 *
 * Note: Uses new Function() intentionally to evaluate admin-defined code for choice type transformations.
 */
export function evaluateToChoices(
  toChoicesCode: string,
  value: string,
  choices: Choice[],
  debug = false,
): EvaluateToChoicesResult {
  if (!toChoicesCode.trim()) {
    if (debug) {
      return { success: false, error: "toChoices 코드가 비어있습니다" };
    }
    return { success: false, error: "내부 오류가 발생하였습니다" };
  }

  try {
    const args = { value, choices };

    const fn = new Function(
      "args",
      `${INVALID_VALUE_ERROR_CLASS}${toChoicesCode.trim()}\n return toChoices(args);`,
    );
    const result = fn(args);

    if (!Array.isArray(result)) {
      if (debug) {
        return {
          success: false,
          error: "toChoices 함수가 배열을 반환하지 않습니다",
        };
      }
      return { success: false, error: "내부 오류가 발생하였습니다" };
    }

    if (!result.every((id) => choices.some((c) => c.localId === id))) {
      if (debug) {
        return {
          success: false,
          error: "toChoices 함수가 유효하지 않은 선택지 ID를 반환합니다",
        };
      }
      return {
        success: false,
        error: "해당 문형에 유효하지 않은 정답입니다",
      };
    }

    return { success: true, choiceIds: result };
  } catch (e) {
    // Check if it's an InvalidValueError (thrown intentionally for invalid input)
    if (e instanceof Error && e.name === INVALID_VALUE_ERROR_MARKER) {
      return {
        success: false,
        invalidValue: true,
        error: e.message,
      };
    }
    return {
      success: false,
      error: e instanceof Error ? e.message : "올바르지 않은 선택지입니다",
    };
  }
}

/**
 * Evaluates the fromChoices JavaScript code with the given choice IDs and choices.
 * The fromChoices code is expected to export a function `fromChoices({ choiceIds, choices })`
 * that returns a display value string.
 *
 * The InvalidValueError class is injected into the scope. User code can throw
 * `new InvalidValueError("message")` to signal invalid input values.
 *
 * Note: Uses new Function() intentionally to evaluate admin-defined code for choice type transformations.
 */
export function evaluateFromChoices(
  fromChoicesCode: string,
  choiceIds: string[],
  choices: Choice[],
): EvaluateFromChoicesResult {
  if (!fromChoicesCode.trim()) {
    return { success: false, error: "fromChoices 코드가 비어있습니다" };
  }

  if (choiceIds.length === 0) {
    return { success: true, value: "" };
  }

  try {
    const args = { choiceIds, choices };

    const fn = new Function(
      "args",
      `${INVALID_VALUE_ERROR_CLASS}${fromChoicesCode.trim()}\n return fromChoices(args);`,
    );
    const result = fn(args);

    if (typeof result !== "string") {
      return {
        success: false,
        error: "fromChoices 함수가 문자열을 반환하지 않습니다",
      };
    }

    return { success: true, value: result };
  } catch (e) {
    // Check if it's an InvalidValueError (thrown intentionally for invalid input)
    if (e instanceof Error && e.name === INVALID_VALUE_ERROR_MARKER) {
      return {
        success: false,
        invalidValue: true,
        error: e.message,
      };
    }
    return {
      success: false,
      error: e instanceof Error ? e.message : "올바르지 않은 선택지입니다",
    };
  }
}

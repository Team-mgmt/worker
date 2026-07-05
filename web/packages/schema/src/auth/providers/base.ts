import z from "zod";

import { ProviderCommonConfigSchema } from "./common.js";
import { GoogleProviderConfigSchema } from "./google.js";
import { MicrosoftProviderConfigSchema } from "./microsoft.js";

export const ProviderConfigSchema = z
  .discriminatedUnion("type", [
    MicrosoftProviderConfigSchema,
    GoogleProviderConfigSchema,
  ])
  .and(ProviderCommonConfigSchema);

export type ProviderConfig = z.infer<typeof ProviderConfigSchema>;

export type GetTokenSuccessResult = {
  readonly result: true;
  readonly token: string;
};

export type GetTokenFailureResult = {
  readonly result: false;
  readonly digest: string;
};

export type GetTokenResult = GetTokenSuccessResult | GetTokenFailureResult;

export type AuthorizeUrlResult = {
  state: string;
  codeVerifier: string;
  url: string;
};

export type GetProfileSuccessResult<T> = {
  readonly result: true;
  readonly profile: T;
};

export type GetProfileFailureResult = {
  readonly result: false;
  readonly digest: string;
};

export type GetProfileResult<T> =
  | GetProfileSuccessResult<T>
  | GetProfileFailureResult;

export type BaseProfile = {
  id: string;
  email: string;
  name: string;
};

export type BaseProfileResult =
  | { result: true; profile: BaseProfile }
  | { result: false; digest: string };

import { Services } from "@shelfalign/schema/dtos/base";

const DEV_URL_MAP: Record<Services, string> = {
  backoffice: "https://dev-backoffice.shelfalign.kr",
};

const STAGING_URL_MAP: Record<Services, string> = {
  backoffice: "https://stg-backoffice.shelfalign.kr",
};

const PROD_URL_MAP: Record<Services, string> = {
  backoffice: "https://backoffice.shelfalign.kr",
};

const LOCAL_URL_MAP: Record<Services, string> = {
  backoffice: "http://localhost:5176",
};

export function getServiceBaseUrl(service: Services, env: string) {
  if (env === "production") {
    return PROD_URL_MAP[service];
  }

  if (env === "staging") {
    return STAGING_URL_MAP[service];
  }

  if (env === "development") {
    return DEV_URL_MAP[service];
  }

  return LOCAL_URL_MAP[service];
}

export type UUIDv4 =
  `${string}-${string}-4${string}-${"8" | "9" | "A" | "B" | "a" | "b"}${string}-${string}`;

export type UUIDv7 =
  `${string}-${string}-7${string}-${"8" | "9" | "A" | "B" | "a" | "b"}${string}-${string}`;

export const NAMESPACES = {
  organization: "b6c0b6e2-f693-4d42-8ca4-c20fcea17c4c",
  memberSet: "bd009c40-7f58-4934-9986-3e908399fcc9",
  user: "b18b7c45-d649-44a4-92b1-3a9f4ee940f3",
} as const;

export const RELATIONS = {
  admin: "fa601a74-6da8-450c-9fd9-2e87b1c1b2ef",
  memberSetMember: "ffefbb67-d096-4cf3-be7f-26399b00dbdb",
  owner: "30f9746d-e7bd-46d6-8ebc-0e14c92ed7db",
} as const;

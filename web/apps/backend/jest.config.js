/** @type {import('jest').Config} */
const config = {
  moduleFileExtensions: ["js", "json", "ts"],
  rootDir: ".",
  testRegex: ".*\\.spec\\.ts$",
  transform: {
    "^.+\\.(t|j)s$": [
      "@swc/jest",
      {
        jsc: {
          parser: {
            syntax: "typescript",
            decorators: true,
          },
          transform: {
            decoratorMetadata: true,
          },
        },
      },
    ],
  },
  // Transform ESM modules that use non-standard JavaScript syntax
  transformIgnorePatterns: [
    "<rootDir>/node_modules/",
    "<rootDir>/../../node_modules/(?!jose|uuid)",
  ],
  collectCoverageFrom: ["src/**/*.(t|j)s", "!src/**/*.schema.ts", "!src/main.ts"],
  coverageDirectory: "./coverage",
  coverageReporters: ["text", "json-summary", "json", "lcov"],
  testEnvironment: "node",
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
    "^jose$": "<rootDir>/test/mocks/jose.mock.ts",
  },
  setupFilesAfterEnv: ["<rootDir>/test/setup.ts"],
  testTimeout: 10000,
};

module.exports = config;

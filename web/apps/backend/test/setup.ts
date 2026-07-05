// Jest test setup file
// This file runs before each test file

// Clear all mocks after each test
afterEach(() => {
  jest.clearAllMocks();
});

// Reset all mocks after all tests
afterAll(() => {
  jest.resetAllMocks();
});

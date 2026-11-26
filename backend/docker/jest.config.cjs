module.exports = {
  rootDir: "/workspace",
  testMatch: ["**/target.test.[jt]s"],
  testEnvironment: "node",
  cacheDirectory: "/tmp/jest-cache",
  moduleDirectories: ["/opt/runner/node_modules", "node_modules"],
  transform: { "^.+\\.[jt]s$": "/opt/runner/jest-transform.cjs" },
};

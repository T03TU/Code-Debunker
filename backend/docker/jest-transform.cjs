// Transpile syntax only. Generated tests are evaluated by Jest inside the sandbox.
const ts = require("/opt/runner/node_modules/typescript");
module.exports = {
  process(source, filename) {
    const result = ts.transpileModule(source, {
      fileName: filename,
      compilerOptions: {
        allowJs: true,
        isolatedModules: true,
        target: ts.ScriptTarget.ES2020,
        module: ts.ModuleKind.CommonJS,
        esModuleInterop: true,
        sourceMap: true,
        inlineSources: true,
      },
    });
    return { code: result.outputText, map: result.sourceMapText };
  },
};

// Minimal vscode module mock for unit tests running outside VS Code.
export const CancellationTokenSource = class {
  token = { isCancellationRequested: false };
  cancel() { this.token.isCancellationRequested = true; }
  dispose() {}
};

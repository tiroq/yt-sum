/** Whether data received from the server may replace the Settings form draft. */
export function shouldApplySettingsRefresh(hasLocalEdits: boolean): boolean {
  return !hasLocalEdits;
}

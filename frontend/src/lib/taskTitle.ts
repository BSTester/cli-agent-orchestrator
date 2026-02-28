export const TASK_TITLE_MAX_LEN = 48;
export const TASK_TITLE_FALLBACK_LEN = 20;

export function summarizeTaskTitle(text: string): string {
  const normalized = text.replace(/\r\n/g, "\n").trim();
  if (!normalized) {
    return "";
  }

  const firstLine = normalized.split("\n").find((line) => line.trim()) || "";
  const compact = firstLine.replace(/\s+/g, " ").trim();

  if (!compact) {
    return normalized.slice(0, TASK_TITLE_FALLBACK_LEN);
  }

  if (compact.length <= TASK_TITLE_MAX_LEN) {
    return compact;
  }

  return `${compact.slice(0, TASK_TITLE_MAX_LEN)}...`;
}

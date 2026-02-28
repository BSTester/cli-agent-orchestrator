const STATUS_LABELS: Record<string, string> = {
  idle: "空闲",
  processing: "处理中",
  completed: "已完成",
  waiting_user_answer: "等待用户输入",
  error: "异常",
};

const INACTIVE_STATUS = new Set([
  "idle",
  "completed",
  "unknown",
  "error",
  "failed",
  "stopped",
  "exited",
]);

export function toStatusLabel(status: string | undefined): string {
  if (!status) {
    return "未知";
  }
  const normalized = status.toLowerCase();
  return STATUS_LABELS[normalized] || status;
}

export function isStatusActive(status: string | undefined): boolean {
  if (!status) {
    return false;
  }
  return !INACTIVE_STATUS.has(status.toLowerCase());
}

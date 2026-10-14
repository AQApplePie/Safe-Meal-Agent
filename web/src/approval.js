export function approvalState(message) {
  if (!message.metadata?.approval_id && !message.metadata?.approval_required && !message.metadata?.approval_state) return null;
  if (message.turnStatus === "processing") return "processing";
  if (message.turnStatus === "failed" || message.metadata?.approval_state === "failed") return "failed";
  if (message.metadata?.approval_required) return "pending";
  return message.metadata?.approval_state || null;
}

export function approvalPayload(message, sessionId, approved) {
  if (approvalState(message) !== "pending" || !message.metadata?.approval_id || !/^\d+$/.test(String(message.id)) || !sessionId) {
    throw new Error("审批已失效，请重新加载会话确认状态。");
  }
  return { session_id: sessionId, message_id: Number(message.id), approval_id: message.metadata.approval_id, approved };
}

export function rememberedSession(raw, apiBase, identity) {
  try {
    const value = JSON.parse(raw || "null");
    return value?.apiBase === apiBase && value?.subject === identity?.subject && value?.tenant === identity?.tenant_id && typeof value?.sessionId === "string" ? value.sessionId : "";
  } catch { return ""; }
}

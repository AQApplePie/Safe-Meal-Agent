import { approvalState } from "../approval";

const labels = { generate_recipe: "生成食谱", recommend_recipes: "推荐食谱", search_recipes: "查询食谱" };
export default function ApprovalCard({ message, busy, onDecision }) {
  const state = approvalState(message);
  if (!state) return null;
  if (state !== "pending") return <div className="approval-status" role="status">{state === "processing" ? "正在恢复操作，请等待并重新加载会话查看结果。" : state === "failed" ? "执行结果尚未确认，已禁止重复提交。请保留此会话交由维护者核查。" : state === "rejected" ? "已拒绝，相关工具未执行。" : "已确认，操作已完成。"}</div>;
  const calls = Array.isArray(message.metadata?.pending_calls) ? message.metadata.pending_calls : [];
  return <section className="approval-card" aria-label="待确认操作">
    <h3>确认后继续</h3><p>以下操作已经暂停。请检查用途与参数，再决定是否继续。</p>
    {calls.map((call, index) => <div className="approval-operation" key={call.id || index}><strong>{labels[call.tool_name] || call.tool_name}</strong>{call.purpose && <p>{call.purpose}</p>}<details><summary>查看操作参数</summary><pre>{JSON.stringify(call.arguments || {}, null, 2)}</pre></details></div>)}
    <div className="approval-actions"><button disabled={busy || !message.metadata?.approval_id || calls.length === 0} onClick={() => onDecision(message, true)}>确认执行</button><button disabled={busy || !message.metadata?.approval_id || calls.length === 0} onClick={() => onDecision(message, false)}>拒绝操作</button></div>
    {calls.length === 0 && <p role="alert">操作预览缺失，请重新加载会话后确认。</p>}
    {!message.metadata?.approval_id && <p role="alert">旧会话缺少审批标识，不能安全恢复。请新建会话。</p>}
  </section>;
}

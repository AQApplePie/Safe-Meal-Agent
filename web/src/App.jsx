import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Bot,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  UserRound,
} from "lucide-react";

import {
  apiRequest,
  buildUrl,
  DEFAULT_API_BASE,
  normalizeBaseUrl,
  streamSse,
} from "./api";

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

export default function App() {
  const [apiBase, setApiBase] = useState(
    () => localStorage.getItem("safemeal-api-base") || DEFAULT_API_BASE,
  );
  const [health, setHealth] = useState("checking");
  const [input, setInput] = useState("推荐一道适合新手、30分钟内完成的晚餐。");
  const [sessionId, setSessionId] = useState("");
  const [userId, setUserId] = useState("react_tester");
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem("safemeal-api-key") || "safemeal-local-api-key",
  );
  const [messages, setMessages] = useState([]);
  const [sending, setSending] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [notice, setNotice] = useState("");

  async function refreshHealth() {
    setHealth("checking");
    try {
      const { data } = await apiRequest(apiBase, "/health");
      setHealth(data.status === "alive" ? "online" : "offline");
    } catch {
      setHealth("offline");
    }
  }

  useEffect(() => {
    refreshHealth();
    // API地址变更时重新探测，函数只依赖当前apiBase。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  function updateApiBase(value) {
    setApiBase(value);
    localStorage.setItem("safemeal-api-base", value);
  }

  function updateApiKey(value) {
    setApiKey(value);
    localStorage.setItem("safemeal-api-key", value);
  }

  function authHeaders(contentType = false) {
    const headers = {
      "X-SafeMeal-User-ID": userId || "default_user",
    };
    if (apiKey) {
      headers["X-API-Key"] = apiKey;
    }
    if (contentType) {
      headers["Content-Type"] = "application/json";
    }
    return headers;
  }

  async function sendMessage(event) {
    event?.preventDefault();
    const question = input.trim();
    if (!question || sending) return;
    const userMessageId = crypto.randomUUID();
    const assistantMessageId = `stream-${crypto.randomUUID()}`;
    const requestId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      { id: userMessageId, role: "user", content: question },
      {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        streaming: true,
        sessionId: sessionId || null,
      },
    ]);
    setInput("");
    setSending(true);
    setNotice("");
    try {
      let completion = null;
      const { elapsed } = await streamSse(apiBase, "/api/v1/chat/stream", {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          message: question,
          session_id: sessionId || null,
          user_id: userId || "default_user",
          request_id: requestId,
        }),
      }, async ({ event: eventName, data }) => {
        if (eventName === "answer") {
          const delta = typeof data === "object" && data ? data.delta || "" : String(data);
          setMessages((current) => current.map((message) =>
            message.id === assistantMessageId
              ? { ...message, content: message.content + delta }
              : message
          ));
        } else if (eventName === "degraded") {
          setNotice("首包等待时间较长，服务仍在继续生成答案。");
        } else if (eventName === "error") {
          const code = typeof data === "object" && data ? data.error_code : "stream_failed";
          throw new Error(`流式回答失败：${code || "stream_failed"}`);
        } else if (eventName === "done") {
          completion = data;
        }
      });
      if (!completion || completion.status !== "ok") {
        throw new Error("流式回答未返回完成事件");
      }
      setSessionId(completion.session_id);
      setMessages((current) => current.map((message) =>
        message.id === assistantMessageId
          ? {
              ...message,
              id: completion.message_id,
              route: completion.route,
              sources: completion.sources || [],
              elapsed,
              sessionId: completion.session_id,
              streaming: false,
              degraded: Boolean(completion.degraded),
            }
          : message
      ));
    } catch (error) {
      setMessages((current) => current.map((message) =>
        message.id === assistantMessageId
          ? {
              ...message,
              role: message.content ? "assistant" : "error",
              content: message.content || error.message,
              streamError: error.message,
              streaming: false,
            }
          : message
      ));
      setNotice(error.message);
    } finally {
      setSending(false);
    }
  }

  async function loadHistory() {
    if (!sessionId) {
      setNotice("请先输入会话ID，或发送一条消息自动创建会话。");
      return;
    }
    setHistoryLoading(true);
    try {
      const query = new URLSearchParams({
        user_id: userId || "default_user",
        limit: "100",
        offset: "0",
      });
      const { data } = await apiRequest(
        apiBase,
        `/api/v1/chat/history/${encodeURIComponent(sessionId)}?${query}`,
        { headers: authHeaders() },
      );
      setMessages(
        data.map((item) => {
          return {
            id: String(item.id),
            role:
              item.message_type === "agent_response"
                ? "assistant"
                : item.message_type === "error"
                  ? "error"
                  : "user",
            content: item.content,
            sessionId: item.session_id,
            route: item.message_metadata?.route,
            sources: item.message_metadata?.sources || [],
          };
        }),
      );
      setNotice(`已载入${data.length}条历史消息。`);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function clearHistory() {
    if (!sessionId || !window.confirm("确认清空当前会话的全部消息吗？")) return;
    try {
      const query = new URLSearchParams({ user_id: userId || "default_user" });
      await apiRequest(apiBase, `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}?${query}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      setMessages([]);
      setNotice("会话消息已清空。");
    } catch (error) {
      setNotice(error.message);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand"><Bot size={24} /><strong>SafeMeal Agent</strong></div>
        <div className="connection">
          <input
            aria-label="API地址"
            value={apiBase}
            onChange={(event) => updateApiBase(event.target.value)}
          />
          <button onClick={refreshHealth} aria-label="重新检查服务"><RefreshCw size={16} /></button>
          <span className={`health ${health}`}>{health === "online" ? "在线" : health === "checking" ? "检查中" : "离线"}</span>
          <a href={buildUrl(normalizeBaseUrl(apiBase), "/docs")} target="_blank" rel="noreferrer">API文档 <ExternalLink size={14} /></a>
        </div>
      </header>

      <section className="hero">
        <span>RECIPE AGENT</span>
        <h1>从食材约束到一份可靠菜谱</h1>
        <p>对话直接进入唯一Agent、类型化工具和确定性饮食安全规则。</p>
      </section>

      <section className="chat-card">
        <div className="chat-toolbar">
          <label>用户ID<input value={userId} onChange={(event) => setUserId(event.target.value)} /></label>
          <label>API Key<input type="password" value={apiKey} onChange={(event) => updateApiKey(event.target.value)} /></label>
          <label>会话ID<input value={sessionId} onChange={(event) => setSessionId(event.target.value)} placeholder="首次对话后生成" /></label>
          <button onClick={loadHistory} disabled={historyLoading}><RefreshCw size={15} />读取历史</button>
          <button className="danger" onClick={clearHistory}><Trash2 size={15} />清空</button>
        </div>

        <div className="messages">
          {messages.length === 0 && (
            <div className="empty"><Sparkles size={28} /><h2>问一个真实的菜谱问题</h2><p>例如：生成一道2人份、30分钟内、不含花生的素菜。</p></div>
          )}
          {messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <span className="avatar">{message.role === "user" ? <UserRound size={17} /> : message.role === "error" ? <AlertTriangle size={17} /> : <Bot size={17} />}</span>
              <div>
                <header><strong>{message.role === "user" ? "你" : message.role === "error" ? "请求错误" : "SafeMeal Agent"}</strong>{message.route && <span>{message.route}</span>}{message.elapsed != null && <span>{message.elapsed}ms</span>}{message.degraded && <span>首包降级</span>}</header>
                <p>{message.content}{message.streaming && <span className="stream-caret" aria-label="正在生成" />}</p>
                {message.streamError && message.role !== "error" && <div className="stream-error">{message.streamError}</div>}
                {message.sources?.length > 0 && <details><summary>查看{message.sources.length}条来源</summary><pre>{pretty(message.sources)}</pre></details>}
              </div>
            </article>
          ))}
          {sending && <div className="thinking"><LoaderCircle className="spin" size={18} />Agent正在规划与调用工具…</div>}
        </div>

        {notice && <div className="notice">{notice}</div>}
        <form className="composer" onSubmit={sendMessage}>
          <textarea value={input} onChange={(event) => setInput(event.target.value)} rows={3} placeholder="输入菜谱、食材或饮食约束问题" />
          <button type="submit" disabled={!input.trim() || sending}><Send size={18} />发送</button>
        </form>
      </section>
    </main>
  );
}

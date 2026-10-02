import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight, Bot, CheckCircle2, ChefHat, Clock3, ExternalLink,
  KeyRound, LoaderCircle, LogOut, Menu, MessageSquarePlus, RefreshCw,
  Send, ShieldCheck, Sparkles, Trash2, UserRound, X,
} from "lucide-react";
import { ApiError, apiRequest, buildUrl, DEFAULT_API_BASE, normalizeBaseUrl, streamSse } from "./api";

const ACCESS_KEY = "safemeal-access-token";
const REFRESH_KEY = "safemeal-refresh-token";

function tokenExpiresSoon(token) {
  try {
    const value = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const encoded = value.padEnd(Math.ceil(value.length / 4) * 4, "=");
    const payload = JSON.parse(atob(encoded));
    return !payload.exp || payload.exp * 1000 < Date.now() + 30_000;
  } catch { return true; }
}

function errorMessage(error) {
  if (error instanceof ApiError && error.status === 401) return "登录状态已失效，请重新登录。";
  if (error instanceof ApiError && error.status === 409) return "该邮箱已经注册，请直接登录。";
  if (error instanceof ApiError && error.status === 422) return "请检查输入。注册密码至少 12 位，并包含字母和数字。";
  return error?.message || "请求失败，请稍后重试。";
}

function RecipeCard({ recipe }) {
  if (!recipe) return null;
  return <section className="recipe-card">
    <div className="recipe-heading">
      <div><span className="eyebrow">结构化食谱</span><h3>{recipe.name}</h3><p>{recipe.description}</p></div>
      <div className="recipe-facts"><span><Clock3 size={15} />{recipe.total_time_minutes} 分钟</span><span><UserRound size={15} />{recipe.servings} 人份</span></div>
    </div>
    <div className="recipe-columns">
      <div><h4>食材</h4><ul>{recipe.ingredients?.map((item) => <li key={`${item.name}-${item.unit}`}><strong>{item.name}</strong><span>{item.quantity} {item.unit}</span></li>)}</ul></div>
      <div><h4>步骤</h4><ol>{recipe.steps?.map((step) => <li key={step.number}>{step.instruction}</li>)}</ol></div>
    </div>
  </section>;
}

function AuthScreen({ apiBase, onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault(); setSubmitting(true); setError("");
    try {
      const body = { email: email.trim(), password };
      if (mode === "register" && displayName.trim()) body.display_name = displayName.trim();
      const { data } = await apiRequest(apiBase, `/api/v1/auth/${mode}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      onAuthenticated(data);
    } catch (requestError) { setError(errorMessage(requestError)); }
    finally { setSubmitting(false); }
  }

  return <main className="auth-page">
    <section className="auth-story">
      <div className="brand-mark"><ChefHat size={26} /><span>SafeMeal</span></div>
      <div className="story-copy">
        <span className="eyebrow">你的饮食约束，应该被认真对待</span>
        <h1>安心提问，<br />放心下厨。</h1>
        <p>结合长期偏好、过敏信息和结构化食谱证据，为每一次推荐做安全复核。</p>
        <div className="trust-list"><span><ShieldCheck size={18} />过敏与忌口前置约束</span><span><CheckCircle2 size={18} />推荐结果二次审查</span><span><Sparkles size={18} />连续对话与长期记忆</span></div>
      </div>
      <p className="story-foot">Recipe intelligence, with safety built in.</p>
    </section>
    <section className="auth-panel"><form className="auth-form" onSubmit={submit}>
      <div className="auth-icon"><KeyRound size={23} /></div><span className="eyebrow">{mode === "login" ? "欢迎回来" : "创建账号"}</span>
      <h2>{mode === "login" ? "登录 SafeMeal" : "开始你的安全食谱档案"}</h2>
      <p>{mode === "login" ? "继续上一次对话和饮食偏好。" : "注册后即可开始提问，账号会自动登录。"}</p>
      {mode === "register" && <label>昵称（选填）<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={100} placeholder="怎么称呼你" /></label>}
      <label>邮箱<input type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" /></label>
      <label>密码<input type="password" required minLength={mode === "register" ? 12 : 1} autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === "register" ? "至少 12 位，包含字母和数字" : "输入密码"} /></label>
      {error && <div className="form-error">{error}</div>}
      <button className="primary-action" disabled={submitting}>{submitting && <LoaderCircle className="spin" size={18} />}{mode === "login" ? "登录" : "注册并登录"}<ArrowRight size={18} /></button>
      <button type="button" className="text-action" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>{mode === "login" ? "还没有账号？立即注册" : "已有账号？返回登录"}</button>
    </form></section>
  </main>;
}

export default function App() {
  const [apiBase, setApiBase] = useState(() => localStorage.getItem("safemeal-api-base") || DEFAULT_API_BASE);
  const [accessToken, setAccessToken] = useState(() => sessionStorage.getItem(ACCESS_KEY) || "");
  const [refreshToken, setRefreshToken] = useState(() => sessionStorage.getItem(REFRESH_KEY) || "");
  const [identity, setIdentity] = useState(null);
  const [authState, setAuthState] = useState(accessToken ? "checking" : "anonymous");
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const messagesEndRef = useRef(null);
  const displayName = useMemo(() => identity?.display_name || identity?.email?.split("@")[0] || "用户", [identity]);

  function storeTokens(tokens) {
    sessionStorage.setItem(ACCESS_KEY, tokens.access_token); sessionStorage.setItem(REFRESH_KEY, tokens.refresh_token);
    setAccessToken(tokens.access_token); setRefreshToken(tokens.refresh_token);
  }
  function clearIdentity() {
    sessionStorage.removeItem(ACCESS_KEY); sessionStorage.removeItem(REFRESH_KEY);
    setAccessToken(""); setRefreshToken(""); setIdentity(null); setAuthState("anonymous"); setSessions([]); setMessages([]); setSessionId("");
  }
  async function refreshAccess(currentRefresh = refreshToken) {
    if (!currentRefresh) throw new ApiError(401, "缺少刷新令牌");
    const { data } = await apiRequest(apiBase, "/api/v1/auth/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: currentRefresh }) });
    storeTokens(data); return data.access_token;
  }
  async function validAccess() { return accessToken && !tokenExpiresSoon(accessToken) ? accessToken : refreshAccess(); }
  async function authed(path, options = {}) {
    let token = await validAccess();
    const invoke = () => apiRequest(apiBase, path, { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` } });
    try { return await invoke(); } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
      token = await refreshAccess(); return invoke();
    }
  }
  async function verifyIdentity(token = accessToken, refresh = refreshToken) {
    if (!token && !refresh) { setAuthState("anonymous"); return; }
    setAuthState("checking");
    try {
      let active = token;
      if (!active || tokenExpiresSoon(active)) active = await refreshAccess(refresh);
      const { data } = await apiRequest(apiBase, "/api/v1/auth/me", { headers: { Authorization: `Bearer ${active}` } });
      setIdentity(data); setAuthState("authenticated");
    } catch { clearIdentity(); }
  }
  async function loadSessions() {
    try { const { data } = await authed("/api/v1/chat/sessions?limit=50&active_only=true"); setSessions(data); }
    catch (error) { setNotice(errorMessage(error)); }
  }

  useEffect(() => { verifyIdentity(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (authState === "authenticated") loadSessions(); }, [authState]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, sending]);

  function handleAuthenticated(tokens) {
    storeTokens(tokens);
    setIdentity({ subject: tokens.user.id, tenant_id: tokens.user.tenant_id, roles: tokens.user.roles || [], provider: "local", email: tokens.user.email, display_name: tokens.user.display_name, status: tokens.user.status });
    setAuthState("authenticated");
  }
  async function logout() {
    try { if (refreshToken) await apiRequest(apiBase, "/api/v1/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: refreshToken }) }); }
    finally { clearIdentity(); }
  }
  function newChat() { setSessionId(""); setMessages([]); setNotice(""); setSidebarOpen(false); }
  async function openSession(id) {
    setSessionId(id); setSidebarOpen(false); setNotice("");
    try {
      const { data } = await authed(`/api/v1/chat/history/${encodeURIComponent(id)}?limit=100&offset=0`);
      setMessages(data.map((item) => ({ id: String(item.id), role: item.message_type === "agent_response" ? "assistant" : item.message_type === "error" ? "error" : "user", content: item.content, route: item.message_metadata?.route, sources: item.message_metadata?.sources || [], recipe: item.message_metadata?.recipe || null })));
    } catch (error) { setNotice(errorMessage(error)); }
  }
  async function deleteSession() {
    if (!sessionId || !window.confirm("确定删除这个会话吗？")) return;
    try { await authed(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }); newChat(); await loadSessions(); }
    catch (error) { setNotice(errorMessage(error)); }
  }
  async function sendMessage(event) {
    event.preventDefault(); const question = input.trim(); if (!question || sending) return;
    const userId = crypto.randomUUID(); const answerId = `stream-${crypto.randomUUID()}`; const requestId = crypto.randomUUID();
    setMessages((items) => [...items, { id: userId, role: "user", content: question }, { id: answerId, role: "assistant", content: "", streaming: true }]);
    setInput(""); setSending(true); setNotice("正在理解你的需求…");
    try {
      const token = await validAccess(); let completion = null;
      await streamSse(apiBase, "/api/v1/chat/stream", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ message: question, session_id: sessionId || null, request_id: requestId }) }, ({ event: name, data }) => {
        if (name === "answer") setMessages((items) => items.map((item) => item.id === answerId ? { ...item, content: item.content + (data?.delta || "") } : item));
        else if (name === "progress") setNotice(data?.message || "正在处理…");
        else if (name === "degraded") setNotice("处理时间较长，仍在继续生成答案…");
        else if (name === "error") throw new Error(data?.message || data?.error_code || "回答生成失败");
        else if (name === "done") completion = data;
      });
      if (!completion || completion.status !== "ok") throw new Error("回答未正常完成");
      setSessionId(completion.session_id);
      setMessages((items) => items.map((item) => item.id === answerId ? { ...item, id: completion.message_id, streaming: false, route: completion.route, sources: completion.sources || [], recipe: completion.recipe } : item));
      setNotice(completion.metadata?.safety_review === "blocked" ? "该建议未通过饮食安全复核，已停止发布食谱。" : ""); await loadSessions();
    } catch (error) {
      setMessages((items) => items.map((item) => item.id === answerId ? { ...item, role: "error", streaming: false, content: item.content || errorMessage(error) } : item)); setNotice(errorMessage(error));
    } finally { setSending(false); }
  }

  if (authState === "checking") return <main className="session-check"><ChefHat size={34} /><LoaderCircle className="spin" size={22} /><span>正在验证登录状态</span></main>;
  if (authState !== "authenticated") return <AuthScreen apiBase={apiBase} onAuthenticated={handleAuthenticated} />;

  return <main className="workspace">
    <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
      <div className="sidebar-brand"><ChefHat size={25} /><span>SafeMeal</span><button className="mobile-close" onClick={() => setSidebarOpen(false)}><X size={19} /></button></div>
      <button className="new-chat" onClick={newChat}><MessageSquarePlus size={18} />新对话</button>
      <div className="session-list"><span className="section-label">最近对话</span>{sessions.length === 0 && <p className="muted">还没有历史对话</p>}{sessions.map((session) => <button key={session.id} className={session.id === sessionId ? "active" : ""} onClick={() => openSession(session.id)}><span>{session.title || "未命名对话"}</span><small>{new Date(session.updated_at || session.created_at).toLocaleDateString("zh-CN")}</small></button>)}</div>
      <div className="sidebar-user"><div className="user-avatar">{displayName.slice(0, 1).toUpperCase()}</div><div><strong>{displayName}</strong><small><ShieldCheck size={12} />身份已验证</small></div><button onClick={logout} title="退出登录"><LogOut size={17} /></button></div>
    </aside>
    {sidebarOpen && <button className="sidebar-scrim" aria-label="关闭侧边栏" onClick={() => setSidebarOpen(false)} />}
    <section className="chat-workspace">
      <header className="workspace-header"><button className="mobile-menu" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><div><span className="eyebrow">SAFE RECIPE ASSISTANT</span><h1>{sessionId ? sessions.find((item) => item.id === sessionId)?.title || "食谱对话" : "新的食谱对话"}</h1></div><div className="header-actions">{sessionId && <button onClick={deleteSession} title="删除会话"><Trash2 size={18} /></button>}<button onClick={() => setSettingsOpen(!settingsOpen)} title="连接设置"><RefreshCw size={18} /></button></div></header>
      {settingsOpen && <div className="connection-panel"><label>后端地址<input value={apiBase} onChange={(event) => { setApiBase(event.target.value); localStorage.setItem("safemeal-api-base", event.target.value); }} /></label><button onClick={() => verifyIdentity()}><ShieldCheck size={16} />重新验证</button><a href={buildUrl(normalizeBaseUrl(apiBase), "/docs")} target="_blank" rel="noreferrer">API 文档<ExternalLink size={14} /></a></div>}
      <div className="conversation">
        {messages.length === 0 && <div className="welcome-state"><div className="welcome-icon"><Bot size={30} /></div><span className="eyebrow">今天想吃什么？</span><h2>告诉我你的食材、时间和饮食要求</h2><p>我会结合你的偏好和过敏信息检索或生成食谱，并在返回前再次进行安全审查。</p><div className="suggestions">{["推荐一道 30 分钟内的清淡晚餐", "我对花生过敏，想吃高蛋白午餐", "用鸡蛋和番茄做一道适合新手的菜"].map((text) => <button key={text} onClick={() => setInput(text)}>{text}<ArrowRight size={15} /></button>)}</div></div>}
        {messages.map((message) => <article key={message.id} className={`chat-message ${message.role}`}><div className="message-avatar">{message.role === "user" ? <UserRound size={17} /> : <ChefHat size={18} />}</div><div className="message-body"><div className="message-meta"><strong>{message.role === "user" ? "你" : message.role === "error" ? "请求未完成" : "SafeMeal"}</strong>{message.route && <span>{message.route}</span>}</div><p>{message.content}{message.streaming && <span className="stream-caret" />}</p><RecipeCard recipe={message.recipe} />{message.sources?.length > 0 && <details><summary>查看 {message.sources.length} 条证据来源</summary><pre>{JSON.stringify(message.sources, null, 2)}</pre></details>}</div></article>)}
        {sending && <div className="working"><LoaderCircle className="spin" size={18} />Agent 正在规划、查询并审查结果</div>}<div ref={messagesEndRef} />
      </div>
      <div className="composer-shell">{notice && <div className="notice">{notice}</div>}<form className="composer" onSubmit={sendMessage}><textarea rows={2} maxLength={5000} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="描述你想吃的菜，或告诉我食材、时间、过敏与忌口…" /><button disabled={!input.trim() || sending} title="发送"><Send size={19} /></button></form><small>食谱建议会经过约束合并和结果复核；严重过敏请同时咨询专业医生。</small></div>
    </section>
  </main>;
}

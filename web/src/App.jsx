import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight, Bot, CheckCircle2, ChefHat, ExternalLink,
  KeyRound, LoaderCircle, LogOut, Menu, MessageSquarePlus, RefreshCw,
  Send, ShieldCheck, Sparkles, Trash2, UserRound, X, BookOpen, Bookmark, History, TrendingUp,
} from "lucide-react";
import { ApiError, apiRequest, buildUrl, DEFAULT_API_BASE, normalizeBaseUrl, streamSse } from "./api";

import ApprovalCard from "./components/ApprovalCard";
import { approvalPayload, approvalState, rememberedSession } from "./approval";
import RecipeWorkspace from "./components/RecipeWorkspace";
import RecipeCard from "./components/RecipeContent";

const ACCESS_KEY = "safemeal-access-token";
const REFRESH_KEY = "safemeal-refresh-token";
const ACTIVE_SESSION_KEY = "safemeal-active-session";

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

function AuthScreen({ apiBase, onAuthenticated, connectionPanel }) {
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
    </form>{connectionPanel}</section>
  </main>;
}

export default function App() {
  const [apiBase, setApiBase] = useState(() => localStorage.getItem("safemeal-api-base") || DEFAULT_API_BASE);
  const [accessToken, setAccessToken] = useState(() => sessionStorage.getItem(ACCESS_KEY) || "");
  const [refreshToken, setRefreshToken] = useState(() => sessionStorage.getItem(REFRESH_KEY) || "");
  const [identity, setIdentity] = useState(null);
  const [authState, setAuthState] = useState(accessToken ? "checking" : "anonymous");
  const [page, setPage] = useState("chat");
  const [apiDraft, setApiDraft] = useState(apiBase);
  const credentialRef = useRef({ accessToken, refreshToken });
  const refreshPromiseRef = useRef(null);
  const authEpochRef = useRef(0);
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const navigationEpoch = useRef(0);
  const approvalLock = useRef(false);
  const hasOpenApproval = messages.some((item) => ["pending", "processing", "failed"].includes(approvalState(item)));
  const messagesEndRef = useRef(null);
  const displayName = useMemo(() => identity?.display_name || identity?.email?.split("@")[0] || "用户", [identity]);

  function storeTokens(tokens) {
    credentialRef.current = { accessToken: tokens.access_token, refreshToken: tokens.refresh_token };
    sessionStorage.setItem(ACCESS_KEY, tokens.access_token); sessionStorage.setItem(REFRESH_KEY, tokens.refresh_token);
    setAccessToken(tokens.access_token); setRefreshToken(tokens.refresh_token);
  }
  function clearIdentity() {
    authEpochRef.current += 1;
    navigationEpoch.current += 1;
    sessionStorage.removeItem(ACTIVE_SESSION_KEY);
    credentialRef.current = { accessToken: "", refreshToken: "" };
    refreshPromiseRef.current = null;
    sessionStorage.removeItem(ACCESS_KEY); sessionStorage.removeItem(REFRESH_KEY);
    setPage("chat"); setSending(false); setNotice("");
    setAccessToken(""); setRefreshToken(""); setIdentity(null); setAuthState("anonymous"); setSessions([]); setMessages([]); setSessionId("");
  }
  async function refreshAccess() {
    if (refreshPromiseRef.current) return refreshPromiseRef.current;
    const currentRefresh = credentialRef.current.refreshToken;
    if (!currentRefresh) throw new ApiError(401, "缺少刷新令牌");
    const epoch = authEpochRef.current;
    const promise = (async () => {
      try {
        const { data } = await apiRequest(apiBase, "/api/v1/auth/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: currentRefresh }) });
        if (authEpochRef.current !== epoch) throw new ApiError(401, "登录状态已改变");
        storeTokens(data); return data.access_token;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401 && epoch === authEpochRef.current) clearIdentity();
        throw error;
      }
    })();
    refreshPromiseRef.current = promise;
    try { return await promise; }
    finally { if (refreshPromiseRef.current === promise) refreshPromiseRef.current = null; }
  }
  async function validAccess() {
    const token = credentialRef.current.accessToken;
    return token && !tokenExpiresSoon(token) ? token : refreshAccess();
  }
  async function authed(path, options = {}) {
    const epoch = authEpochRef.current;
    let token = await validAccess();
    const invoke = async () => {
      if (epoch !== authEpochRef.current) throw new ApiError(401, "登录状态已改变");
      const result = await apiRequest(apiBase, path, { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` } });
      if (epoch !== authEpochRef.current) throw new ApiError(401, "登录状态已改变");
      return result;
    };
    try { return await invoke(); } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401 || epoch !== authEpochRef.current) throw error;
      const latest = credentialRef.current.accessToken;
      token = latest && latest !== token ? latest : await refreshAccess();
      try { return await invoke(); }
      catch (retryError) {
        if (retryError instanceof ApiError && retryError.status === 401 && epoch === authEpochRef.current) clearIdentity();
        throw retryError;
      }
    }
  }
  async function verifyIdentity(token = accessToken, refresh = refreshToken) {
    if (!token && !refresh) { setAuthState("anonymous"); return; }
    const epoch = authEpochRef.current;
    setAuthState("checking");
    try {
      let active = token;
      if (!active || tokenExpiresSoon(active)) active = await refreshAccess();
      const { data } = await apiRequest(apiBase, "/api/v1/auth/me", { headers: { Authorization: `Bearer ${active}` } });
      if (epoch !== authEpochRef.current) return;
      setIdentity(data); setAuthState("authenticated");
    } catch { if (epoch === authEpochRef.current) clearIdentity(); }
  }
  async function loadSessions() {
    try { const { data } = await authed("/api/v1/chat/sessions?limit=50&active_only=true"); setSessions(data); }
    catch (error) { setNotice(errorMessage(error)); }
  }

  useEffect(() => { verifyIdentity(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (authState === "authenticated") { loadSessions(); const remembered = rememberedSession(sessionStorage.getItem(ACTIVE_SESSION_KEY), apiBase, identity); if (remembered) openSession(remembered); } }, [authState]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, sending]);

  function handleAuthenticated(tokens) {
    storeTokens(tokens);
    setIdentity({ subject: tokens.user.id, tenant_id: tokens.user.tenant_id, roles: tokens.user.roles || [], provider: "local", email: tokens.user.email, display_name: tokens.user.display_name, status: tokens.user.status });
    setAuthState("authenticated");
  }
  async function logout() {
    const refreshToken = credentialRef.current.refreshToken;
    clearIdentity();
    try { if (refreshToken) await apiRequest(apiBase, "/api/v1/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: refreshToken }) }); }
    catch { /* Local logout is complete even if the server is unavailable. */ }
  }
  function rememberSession(id) { sessionStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify({ sessionId: id, apiBase, subject: identity?.subject, tenant: identity?.tenant_id })); }
  function newChat() { navigationEpoch.current += 1; sessionStorage.removeItem(ACTIVE_SESSION_KEY); setPage("chat"); setSessionId(""); setMessages([]); setNotice(""); setSidebarOpen(false); }
  async function openSession(id) {
    const navigation = ++navigationEpoch.current;
    const epoch = authEpochRef.current;
    rememberSession(id);
    setMessages([]);
    setPage("chat"); setSessionId(id); setSidebarOpen(false); setNotice("");
    try {
      const { data } = await authed(`/api/v1/chat/history/${encodeURIComponent(id)}?limit=100&offset=0`);
      if (navigation !== navigationEpoch.current || epoch !== authEpochRef.current) return;
      setMessages(data.map((item) => ({ id: String(item.id), role: item.message_type === "agent_response" ? "assistant" : item.message_type === "error" ? "error" : "user", content: item.content, route: item.message_metadata?.route, sources: item.message_metadata?.sources || [], recipe: item.message_metadata?.recipe || null, metadata: item.message_metadata || {}, turnStatus: item.turn_status })));
    } catch (error) { setNotice(errorMessage(error)); }
  }
  async function deleteSession() {
    if (!sessionId || !window.confirm("确定删除这个会话吗？")) return;
    try { await authed(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }); newChat(); await loadSessions(); }
    catch (error) { setNotice(errorMessage(error)); }
  }
  async function sendMessage(event) {
    event.preventDefault(); const question = input.trim(); if (!question || sending || hasOpenApproval) return;
    const epoch = authEpochRef.current;
    const userId = crypto.randomUUID(); const answerId = `stream-${crypto.randomUUID()}`; const requestId = crypto.randomUUID();
    setMessages((items) => [...items, { id: userId, role: "user", content: question }, { id: answerId, role: "assistant", content: "", streaming: true }]);
    setInput(""); setSending(true); setNotice("正在理解你的需求…");
    try {
      const token = await validAccess(); let completion = null;
      await streamSse(apiBase, "/api/v1/chat/stream", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ message: question, session_id: sessionId || null, request_id: requestId }) }, ({ event: name, data }) => {
        if (epoch !== authEpochRef.current) return;
        if (name === "answer") setMessages((items) => items.map((item) => item.id === answerId ? { ...item, content: item.content + (data?.delta || "") } : item));
        else if (name === "progress") setNotice(data?.message || "正在处理…");
        else if (name === "degraded") setNotice("处理时间较长，仍在继续生成答案…");
        else if (name === "error") throw new Error(data?.message || data?.error_code || "回答生成失败");
        else if (name === "done") completion = data;
      });
      if (epoch !== authEpochRef.current) return;
      if (!completion || completion.status !== "ok") throw new Error("回答未正常完成");
      rememberSession(completion.session_id);
      setSessionId(completion.session_id);
      setMessages((items) => items.map((item) => item.id === answerId ? { ...item, id: completion.message_id, streaming: false, route: completion.route, sources: completion.sources || [], recipe: completion.recipe, metadata: completion.metadata || {} } : item));
      setNotice(completion.metadata?.safety_review === "blocked" ? "该建议未通过饮食安全复核，已停止发布食谱。" : ""); await loadSessions();
    } catch (error) {
      if (epoch !== authEpochRef.current) return;
      setMessages((items) => items.map((item) => item.id === answerId ? { ...item, role: "error", streaming: false, content: item.content || errorMessage(error) } : item)); setNotice(errorMessage(error));
    } finally { if (epoch === authEpochRef.current) setSending(false); }
  }

  async function resumeApproval(message, approved) {
    if (sending || approvalLock.current) return;
    const epoch = authEpochRef.current;
    approvalLock.current = true; setSending(true); setNotice("正在恢复操作…");
    try {
      const body = approvalPayload(message, sessionId, approved);
      const { data } = await authed("/api/v1/chat/resume", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (epoch !== authEpochRef.current) return;
      setMessages((items) => items.map((item) => item.id === message.id ? { ...item, content: data.message, route: data.route, sources: data.sources || [], recipe: data.recipe, metadata: data.metadata || {}, turnStatus: data.status === "error" ? "failed" : null } : item));
      setNotice(data.status === "error" ? "恢复失败，执行结果尚未确认，请勿重复提交。" : data.metadata?.safety_review === "blocked" ? "操作已完成，但食谱未通过安全复核，已停止发布。" : "");
      await loadSessions();
    } catch (error) {
      if (epoch !== authEpochRef.current) return;
      // A lost response may already have executed: reload authoritative history before retry.
      await openSession(sessionId);
      setNotice(`${error.status === 422 ? "审批参数无效，请重新加载当前会话。" : errorMessage(error)} 已重新加载会话状态，请确认操作结果。`);
    } finally {
      approvalLock.current = false;
      if (epoch === authEpochRef.current) setSending(false);
    }
  }

  function applyConnection(event) {
    event.preventDefault();
    const normalized = normalizeBaseUrl(apiDraft);
    try {
      const url = new URL(normalized);
      if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error();
    } catch { setNotice("请输入有效的 HTTP 或 HTTPS 后端地址。"); return; }
    if (normalized !== apiBase) {
      clearIdentity(); setApiBase(normalized); localStorage.setItem("safemeal-api-base", normalized);
      setNotice(""); setSettingsOpen(false);
    } else if (authState === "authenticated") verifyIdentity();
  }
  const connectionPanel = <form className="connection-panel" onSubmit={applyConnection}><label>后端地址<input type="url" required value={apiDraft} onChange={(event) => setApiDraft(event.target.value)} /></label><button type="submit"><ShieldCheck size={16} />保存连接</button><a href={buildUrl(normalizeBaseUrl(apiBase), "/docs")} target="_blank" rel="noreferrer">API 文档<ExternalLink size={14} /></a></form>;

  if (authState === "checking") return <main className="session-check"><ChefHat size={34} /><LoaderCircle className="spin" size={22} /><span>正在验证登录状态</span></main>;
  if (authState !== "authenticated") return <AuthScreen apiBase={apiBase} onAuthenticated={handleAuthenticated} connectionPanel={<details className="login-connection"><summary>连接设置</summary>{connectionPanel}{notice && <p role="alert">{notice}</p>}</details>} />;

  return <main className="workspace">
    <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
      <div className="sidebar-brand"><ChefHat size={25} /><span>SafeMeal</span><button className="mobile-close" aria-label="关闭导航" onClick={() => setSidebarOpen(false)}><X size={19} /></button></div>
      <nav className="workspace-nav" aria-label="主导航">{[["chat", "食谱助手", Bot], ["recipes", "发现食谱", BookOpen], ["rankings", "热门榜单", TrendingUp], ["favorites", "我的收藏", Bookmark], ["history", "最近浏览", History]].map(([key, label, Icon]) => <button key={key} className={page === key ? "active" : ""} aria-current={page === key ? "page" : undefined} onClick={() => { setPage(key); setSidebarOpen(false); }}><Icon size={18} />{label}</button>)}</nav>
      <button className="new-chat" disabled={sending} onClick={newChat}><MessageSquarePlus size={18} />新对话</button>
      <div className="session-list"><span className="section-label">最近对话</span>{sessions.length === 0 && <p className="muted">还没有历史对话</p>}{sessions.map((session) => <button key={session.id} className={session.id === sessionId ? "active" : ""} disabled={sending} onClick={() => openSession(session.id)}><span>{session.title || "未命名对话"}</span><small>{new Date(session.updated_at || session.created_at).toLocaleDateString("zh-CN")}</small></button>)}</div>
      <div className="sidebar-user"><div className="user-avatar">{displayName.slice(0, 1).toUpperCase()}</div><div><strong>{displayName}</strong><small><ShieldCheck size={12} />身份已验证</small></div><button onClick={logout} title="退出登录"><LogOut size={17} /></button></div>
    </aside>
    {sidebarOpen && <button className="sidebar-scrim" aria-label="关闭侧边栏" onClick={() => setSidebarOpen(false)} />}
    {page !== "chat" ? <section className="browse-shell"><header className="browse-topbar"><button className="mobile-menu" aria-label="打开导航" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><span><ShieldCheck size={15} />{displayName} 的厨房</span><button className="icon-button" aria-label="连接设置" onClick={() => setSettingsOpen(!settingsOpen)}><RefreshCw size={18} /></button></header>{settingsOpen && connectionPanel}<RecipeWorkspace key={`${page}:${identity?.subject}`} page={page} request={authed} /></section> : <section className="chat-workspace">
      <header className="workspace-header"><button className="mobile-menu" aria-label="打开导航" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><div><span className="eyebrow">SAFE RECIPE ASSISTANT</span><h1>{sessionId ? sessions.find((item) => item.id === sessionId)?.title || "食谱对话" : "新的食谱对话"}</h1></div><div className="header-actions">{sessionId && <button disabled={sending} onClick={deleteSession} title="删除会话"><Trash2 size={18} /></button>}<button onClick={() => setSettingsOpen(!settingsOpen)} title="连接设置"><RefreshCw size={18} /></button></div></header>
      {settingsOpen && connectionPanel}
      <div className="conversation">
        {messages.length === 0 && <div className="welcome-state"><div className="welcome-icon"><Bot size={30} /></div><span className="eyebrow">今天想吃什么？</span><h2>告诉我你的食材、时间和饮食要求</h2><p>我会结合你的偏好和过敏信息检索或生成食谱，并在返回前再次进行安全审查。</p><div className="suggestions">{["推荐一道 30 分钟内的清淡晚餐", "我对花生过敏，想吃高蛋白午餐", "用鸡蛋和番茄做一道适合新手的菜"].map((text) => <button key={text} onClick={() => setInput(text)}>{text}<ArrowRight size={15} /></button>)}</div></div>}
        {messages.map((message) => <article key={message.id} className={`chat-message ${message.role}`}><div className="message-avatar">{message.role === "user" ? <UserRound size={17} /> : <ChefHat size={18} />}</div><div className="message-body"><div className="message-meta"><strong>{message.role === "user" ? "你" : message.role === "error" ? "请求未完成" : "SafeMeal"}</strong>{message.route && <span>{message.route}</span>}</div><p>{message.content}{message.streaming && <span className="stream-caret" />}</p><RecipeCard recipe={message.recipe} /><ApprovalCard message={message} busy={sending} onDecision={resumeApproval} />{message.sources?.length > 0 && <details><summary>查看 {message.sources.length} 条证据来源</summary><pre>{JSON.stringify(message.sources, null, 2)}</pre></details>}</div></article>)}
        {sending && <div className="working"><LoaderCircle className="spin" size={18} />Agent 正在规划、查询并审查结果</div>}<div ref={messagesEndRef} />
      </div>
      <div className="composer-shell">{notice && <div className="notice">{notice}</div>}<form className="composer" onSubmit={sendMessage}><textarea disabled={sending || hasOpenApproval} rows={2} maxLength={5000} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={hasOpenApproval ? "请先处理本会话待确认的操作，或新建对话" : "描述你想吃的菜，或告诉我食材、时间、过敏与忌口…"} /><button disabled={!input.trim() || sending || hasOpenApproval} title="发送"><Send size={19} /></button></form><small>食谱建议会经过约束合并和结果复核；严重过敏请同时咨询专业医生。</small></div>
    </section>}
  </main>;
}

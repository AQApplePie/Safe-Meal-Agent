import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, Bookmark, ChefHat, Clock3, Heart, History, LoaderCircle, RefreshCw, Search, SlidersHorizontal, TrendingUp, X } from "lucide-react";
import RecipeContent from "./RecipeContent";
import { DIFFICULTIES, EMPTY_FILTERS, formatDate, friendlyError, recipeId, recipeName, recipeSearchPath } from "../recipes";

const TITLES = {
  recipes: ["发现好食谱", "从熟悉的食材出发，找到今天想做的一道菜。", BookOpen],
  favorites: ["我的收藏", "把喜欢的味道留下，下次做饭更有灵感。", Bookmark],
  history: ["最近浏览", "那些看过的做法，都在这里等你回来。", History],
  rankings: ["热门食谱", "看看大家最近在做什么，给餐桌添一点新意。", TrendingUp],
};
const PAGE_SIZE = 12;
const json = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function Reactions({ state, busy, onChange }) {
  if (!state) return <span className="interaction-unavailable">交互状态暂不可用</span>;
  return <div className="reaction-actions">
    <button aria-label={state.liked ? "取消点赞" : "点赞"} aria-pressed={state.liked} disabled={busy} onClick={() => onChange("like", !state.liked)}><Heart size={16} fill={state.liked ? "currentColor" : "none"} /><span>{state.like_count}</span></button>
    <button aria-label={state.favorited ? "取消收藏" : "收藏"} aria-pressed={state.favorited} disabled={busy} onClick={() => onChange("favorite", !state.favorited)}><Bookmark size={16} fill={state.favorited ? "currentColor" : "none"} /><span>{state.favorited ? "已收藏" : "收藏"}</span></button>
  </div>;
}

function RecipeDetail({ id, request, state, busy, onChange, onClose, actionError }) {
  const dialogRef = useRef(null);
  const [recipe, setRecipe] = useState(null);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const viewReported = useRef(false);
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog.showModal();
    return () => { if (dialog.open) dialog.close(); };
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    request(`/api/v1/recipes/${id}`).then(async ({ data }) => {
      if (!active) return;
      setRecipe(data); setLoading(false);
      // Only explicit successful detail opens count; rerenders/retries do not.
      if (!viewReported.current) {
        viewReported.current = true;
        try { await request(`/api/v1/recipes/${id}/view`, { method: "PUT" }); }
        catch (err) { if (active) setWarning(`浏览记录未保存：${friendlyError(err)}`); }
      }
    }).catch((err) => { if (active) { setError(friendlyError(err)); setLoading(false); } });
    return () => { active = false; };
  }, [id, request, attempt]);
  return <dialog ref={dialogRef} className="recipe-dialog" aria-labelledby="detail-title" onCancel={onClose} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="detail-toolbar"><h2 id="detail-title">食谱详情</h2><button className="icon-button" aria-label="关闭食谱详情" onClick={onClose}><X size={20} /></button></div>
    {loading ? <div className="catalog-status" role="status"><LoaderCircle className="spin" />正在加载做法…</div> : error ? <div className="catalog-status"><p role="alert">{error}</p><button onClick={() => setAttempt((n) => n + 1)}>重试</button></div> : <><RecipeContent recipe={recipe} /><div className="detail-bottom"><Reactions state={state} busy={busy} onChange={onChange} /><p>请核对食材与个人过敏、忌口要求。</p></div></>}
    {actionError && <p className="catalog-warning" role="alert">{actionError}</p>}
    {warning && <p className="catalog-warning" role="status">{warning}</p>}
  </dialog>;
}

export default function RecipeWorkspace({ page, request: providedRequest }) {
  const requestRef = useRef(providedRequest);
  requestRef.current = providedRequest;
  const request = useCallback((...args) => requestRef.current(...args), []);
  const [draft, setDraft] = useState({ ...EMPTY_FILTERS });
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS });
  const [mode, setMode] = useState("today");
  const [offset, setOffset] = useState(0);
  const [cursors, setCursors] = useState([null]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [data, setData] = useState(null);
  const [interactions, setInteractions] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const [reload, setReload] = useState(0);
  const [selectedId, setSelectedId] = useState(null);
  const [busy, setBusy] = useState({});
  const pending = useRef(new Set());
  const generation = useRef(0);
  const cursor = cursors[historyIndex];
  const [title, description, Icon] = TITLES[page];

  useEffect(() => {
    let active = true;
    const currentGeneration = ++generation.current;
    setLoading(true); setError(""); setWarning(""); setData(null); setInteractions({});
    let path;
    try {
      path = page === "recipes" ? recipeSearchPath(filters, offset, PAGE_SIZE)
        : page === "history" ? `/api/v1/recipes/history?${new URLSearchParams({ limit: PAGE_SIZE, ...(cursor ? { cursor } : {}) })}`
        : page === "rankings" ? `/api/v1/recipes/rankings?mode=${mode}&offset=${offset}&limit=${PAGE_SIZE}`
        : `/api/v1/recipes/favorites?offset=${offset}&limit=${PAGE_SIZE}`;
    } catch (err) { setError(friendlyError(err)); setLoading(false); return; }
    request(path).then(async ({ data: result }) => {
      if (!active) return;
      setData(result); setLoading(false);
      const ids = result.items.map(recipeId);
      if (!ids.length) return;
      try {
        const { data: states } = await request("/api/v1/recipes/interactions/query", json({ recipe_ids: ids }));
        if (active && currentGeneration === generation.current) {
          setInteractions(Object.fromEntries(states.items.map((item) => [item.recipe_id, item])));
          if (states.missing_recipe_ids.length) setWarning("部分食谱已被删除，请刷新列表。");
        }
      } catch (err) { if (active) setWarning(`点赞与收藏状态加载失败：${friendlyError(err)}`); }
    }).catch((err) => { if (active) { setError(friendlyError(err)); setLoading(false); } });
    return () => { active = false; };
  }, [page, filters, offset, cursor, mode, reload, request]);

  async function changeState(id, kind, enabled) {
    if (pending.current.has(id)) return;
    pending.current.add(id); setBusy((old) => ({ ...old, [id]: true }));
    const currentGeneration = generation.current;
    try {
      const { data: state } = await request(`/api/v1/recipes/${id}/${kind}`, { method: enabled ? "PUT" : "DELETE" });
      if (generation.current !== currentGeneration) return;
      setInteractions((old) => ({ ...old, [id]: state })); setWarning("");
      if (page === "favorites" && kind === "favorite" && !enabled) {
        setSelectedId(null);
        setReload((n) => n + 1);
      }
    } catch (err) { if (generation.current === currentGeneration) setWarning(friendlyError(err)); }
    finally { pending.current.delete(id); setBusy((old) => ({ ...old, [id]: false })); }
  }

  const field = (key, label, props = {}) => <label>{label}<input {...props} value={draft[key]} onChange={(event) => setDraft((old) => ({ ...old, [key]: event.target.value }))} /></label>;
  return <section className="catalog-workspace">
    <header className="catalog-heading"><div><span className="eyebrow">YOUR EVERYDAY KITCHEN</span><h1>{title}</h1><p>{description}</p></div><div className="catalog-heading-icon"><Icon size={32} /></div></header>
    {page === "recipes" && <form className="catalog-filters" onSubmit={(event) => { event.preventDefault(); setOffset(0); setFilters({ ...draft }); }}>
      <div className="search-row"><label className="search-field"><Search size={19} /><input aria-label="搜索食谱" placeholder="搜索食谱名称，例如：番茄炒蛋" maxLength={255} value={draft.name} onChange={(event) => setDraft((old) => ({ ...old, name: event.target.value }))} /></label><button className="solid-button" type="submit">搜索食谱<ArrowRight size={16} /></button></div>
      <details><summary><SlidersHorizontal size={16} />筛选食材、时间与难度</summary><div className="filter-grid">
        {field("cuisine", "菜系", { placeholder: "例如：家常菜", maxLength: 255 })}
        <label>难度<select value={draft.difficulties} onChange={(event) => setDraft((old) => ({ ...old, difficulties: event.target.value }))}><option value="">全部难度</option>{Object.entries(DIFFICULTIES).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
        {field("max_total_time_minutes", "最长用时（分钟）", { type: "number", min: 0, max: 10080, placeholder: "不限" })}
        {field("max_calories", "最高热量（kcal）", { type: "number", min: 0, max: 100000, step: "any", placeholder: "不限" })}
        {field("include_ingredients", "包含食材", { placeholder: "鸡蛋，番茄", maxLength: 2020 })}
        {field("exclude_ingredients", "排除食材", { placeholder: "花生，虾（逗号分隔）", maxLength: 5050 })}
        <label>排序<select value={draft.sort_by} onChange={(event) => setDraft((old) => ({ ...old, sort_by: event.target.value }))}><option value="name">名称 A–Z</option><option value="total_time">用时从短到长</option><option value="total_calories">热量从低到高</option></select></label>
        <div className="filter-actions"><button type="button" onClick={() => { setDraft({ ...EMPTY_FILTERS }); setFilters({ ...EMPTY_FILTERS }); setOffset(0); }}>重置</button><button className="solid-button" type="submit">应用筛选</button></div>
      </div><p>食材筛选仅匹配目录信息，请在详情中核对全部食材。</p></details>
    </form>}
    {page === "rankings" && <div className="ranking-tabs" aria-label="榜单类型"><button aria-pressed={mode === "today"} onClick={() => { setMode("today"); setOffset(0); }}>今日热门</button><button aria-pressed={mode === "popular"} onClick={() => { setMode("popular"); setOffset(0); }}>最受欢迎</button><span>{mode === "today" ? "按今日浏览用户数排序" : "按当前点赞与收藏总数排序"}</span></div>}
    <div className="catalog-meta"><span>{loading ? "正在加载…" : page === "recipes" && data ? `共 ${data.total} 道食谱` : title}{page === "rankings" && data && ` · 更新于 ${formatDate(data.updated_at)}`}</span><button disabled={loading} onClick={() => setReload((n) => n + 1)}><RefreshCw size={15} />刷新</button></div>
    {page === "rankings" && <p className="ranking-note">行为统计稍后更新，可刷新查看最新结果。{data?.truncated && "当前展示榜单前列食谱。"}</p>}
    {warning && <div className="catalog-warning" role="alert">{warning}<button onClick={() => setReload((n) => n + 1)}>重试加载</button></div>}
    {loading ? <div className="catalog-status" role="status"><LoaderCircle className="spin" size={24} /><p>正在准备食谱…</p></div> : error ? <div className="catalog-status"><p role="alert">{error}</p><button className="solid-button" onClick={() => setReload((n) => n + 1)}>重新加载</button></div> : !data?.items.length ? <div className="catalog-status"><Icon size={38} /><h2>{page === "favorites" ? "还没有收藏的食谱" : page === "history" ? "还没有浏览记录" : "暂时没有匹配的食谱"}</h2><p>{page === "favorites" ? "在食谱卡片上点击收藏，喜欢的做法就会出现在这里。" : page === "history" ? "打开一道食谱详情后，会自动保存浏览记录。" : "试着放宽筛选条件，或稍后刷新看看。"}</p>{offset > 0 && <button onClick={() => setOffset(0)}>返回第一页</button>}</div> : <div className="catalog-grid">{data.items.map((item) => {
      const id = recipeId(item);
      return <article className="catalog-card" key={id}>
        <button className="recipe-open" onClick={() => setSelectedId(id)} aria-label={`查看${recipeName(item)}详情`}>
          <div className="recipe-cover"><ChefHat size={42} strokeWidth={1.3} /><span>{page === "rankings" ? `#${item.rank}` : item.cuisine || "日常好味"}</span></div>
          <div className="catalog-card-copy"><h2>{recipeName(item)}</h2><p>{item.description || (page === "history" ? `浏览于 ${formatDate(item.last_viewed_at)}` : page === "favorites" ? `收藏于 ${formatDate(item.favorited_at)}` : page === "rankings" ? `${item.score} ${mode === "today" ? "位浏览用户" : "次点赞与收藏"}` : "查看食材与详细做法")}</p><div className="card-facts">{item.total_time_minutes != null && <span><Clock3 size={14} />{item.total_time_minutes} 分钟</span>}{item.difficulty && <span>{DIFFICULTIES[item.difficulty]}</span>}{item.calories != null && <span>{item.calories} kcal</span>}</div></div>
        </button><div className="catalog-card-footer"><Reactions state={interactions[id]} busy={busy[id]} onChange={(kind, enabled) => changeState(id, kind, enabled)} /></div>
      </article>;
    })}</div>}
    {!loading && !error && data && <nav className="catalog-pagination" aria-label="食谱分页"><button disabled={page === "history" ? historyIndex === 0 : offset === 0} onClick={() => page === "history" ? setHistoryIndex((n) => n - 1) : setOffset((n) => Math.max(0, n - PAGE_SIZE))}><ArrowLeft size={16} />上一页</button><span>第 {page === "history" ? historyIndex + 1 : Math.floor(offset / PAGE_SIZE) + 1} 页</span><button disabled={!data.has_more || (page === "history" ? !data.next_cursor : offset + PAGE_SIZE > (page === "recipes" ? 100000 : 9999))} onClick={() => {
      if (page === "history") { setCursors((old) => [...old.slice(0, historyIndex + 1), data.next_cursor]); setHistoryIndex((n) => n + 1); }
      else setOffset((n) => n + PAGE_SIZE);
    }}>下一页<ArrowRight size={16} /></button></nav>}
    {selectedId != null && <RecipeDetail key={selectedId} id={selectedId} request={request} actionError={warning} state={interactions[selectedId]} busy={busy[selectedId]} onChange={(kind, enabled) => changeState(selectedId, kind, enabled)} onClose={() => setSelectedId(null)} />}
  </section>;
}

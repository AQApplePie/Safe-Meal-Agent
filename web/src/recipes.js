// Frontend adapter for the canonical recipe and interaction HTTP contracts.
export const DIFFICULTIES = { easy: "简单", medium: "适中", hard: "进阶" };
export const EMPTY_FILTERS = { name: "", cuisine: "", difficulties: "", max_total_time_minutes: "", max_calories: "", include_ingredients: "", exclude_ingredients: "", sort_by: "name" };

export function recipeSearchPath(filters, offset = 0, limit = 12) {
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit), sort_by: filters.sort_by, sort_order: "asc" });
  for (const key of ["name", "cuisine", "difficulties", "max_total_time_minutes", "max_calories"]) {
    if (String(filters[key]).trim()) query.set(key, String(filters[key]).trim());
  }
  for (const key of ["include_ingredients", "exclude_ingredients"]) {
    const terms = [...new Set(filters[key].split(/[,，、]/).map((term) => term.trim()).filter(Boolean))];
    const max = key === "include_ingredients" ? 20 : 50;
    if (terms.length > max || terms.some((term) => term.length > 100)) throw new Error(`食材最多 ${max} 项，每项最多 100 字。`);
    terms.forEach((term) => query.append(key, term));
  }
  return `/api/v1/recipes?${query}`;
}

export function recipeId(item) { return item.recipe_id ?? item.id; }
export function recipeName(item) { return item.recipe_name ?? item.name; }
export function ingredientName(item) { return item.ingredient?.name ?? item.name; }
export function friendlyError(error) {
  if (error?.status === 401) return "登录已过期，请重新登录。";
  if (error?.status === 404) return "这道食谱已不存在，请刷新列表。";
  if (error?.status === 422) return "筛选条件不符合要求，请调整后重试。";
  return error?.message || "暂时无法连接服务，请稍后重试。";
}
export function formatDate(value) {
  if (!value) return "";
  // SQL favorites timestamps are naive UTC; history timestamps carry a zone.
  const zoned = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`;
  const date = new Date(zoned);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

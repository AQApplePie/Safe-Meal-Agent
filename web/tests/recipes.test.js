import test from "node:test";
import assert from "node:assert/strict";
import { EMPTY_FILTERS, recipeSearchPath, recipeId, recipeName, ingredientName, friendlyError, formatDate } from "../src/recipes.js";

test("catalog search encodes Chinese and separate repeated ingredient parameters", () => {
  const path = recipeSearchPath({ ...EMPTY_FILTERS, name: " 番茄 & 鸡蛋 ", difficulties: "easy", max_total_time_minutes: "30", include_ingredients: "鸡蛋，番茄,鸡蛋", exclude_ingredients: "花生、虾" }, 12);
  const query = new URL(path, "http://test").searchParams;
  assert.equal(query.get("name"), "番茄 & 鸡蛋");
  assert.equal(query.get("offset"), "12");
  assert.equal(query.get("sort_by"), "name");
  assert.equal(query.get("max_total_time_minutes"), "30");
  assert.deepEqual(query.getAll("include_ingredients"), ["鸡蛋", "番茄"]);
  assert.deepEqual(query.getAll("exclude_ingredients"), ["花生", "虾"]);
});

test("numeric zero filters are retained while empty values are omitted", () => {
  const query = new URL(recipeSearchPath({ ...EMPTY_FILTERS, max_calories: "0" }), "http://test").searchParams;
  assert.equal(query.get("max_calories"), "0");
  assert.equal(query.has("name"), false);
  assert.equal(query.has("difficulties"), false);
});

test("ingredient limits fail before issuing an invalid backend query", () => {
  assert.throws(() => recipeSearchPath({ ...EMPTY_FILTERS, include_ingredients: Array.from({ length: 21 }, (_, i) => `食材${i}`).join(",") }));
  assert.throws(() => recipeSearchPath({ ...EMPTY_FILTERS, exclude_ingredients: "长".repeat(101) }));
});

test("catalog and personal list contracts use their own canonical names and IDs", () => {
  assert.equal(recipeId({ id: 3 }), 3);
  assert.equal(recipeId({ recipe_id: 4 }), 4);
  assert.equal(recipeName({ name: "番茄炒蛋" }), "番茄炒蛋");
  assert.equal(recipeName({ recipe_name: "番茄炒蛋" }), "番茄炒蛋");
  assert.equal(ingredientName({ ingredient: { name: "番茄" } }), "番茄");
  assert.equal(ingredientName({ name: "番茄" }), "番茄");
});

test("request failures distinguish deleted recipes and expired identity", () => {
  assert.match(friendlyError({ status: 401 }), /登录/);
  assert.match(friendlyError({ status: 404 }), /不存在/);
  assert.match(friendlyError({ status: 422 }), /筛选/);
  assert.equal(friendlyError(new Error("断开连接")), "断开连接");
});

test("naive SQL favorite time and aware history time represent the same instant", () => {
  assert.equal(formatDate("2026-10-09T08:00:00"), formatDate("2026-10-09T08:00:00Z"));
  assert.equal(formatDate("2026-10-09T16:00:00+08:00"), formatDate("2026-10-09T08:00:00Z"));
  assert.equal(formatDate("invalid"), "");
});

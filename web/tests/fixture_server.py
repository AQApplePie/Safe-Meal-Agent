"""Disposable UI contract fixture. Never a production/authentication server.

Run: python web/tests/fixture_server.py
Only localhost:18080, in-memory synthetic data; no project DB or external service.
"""
import base64
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RECIPES = [dict(id=i, name=name, description=description, total_time_minutes=15+i,
                servings=2, difficulty="easy", cuisine="家常菜", calories="320")
           for i, (name, description) in enumerate([
               ("番茄炒蛋", "酸甜番茄遇上嫩滑鸡蛋，一道简单的日常好味。"),
               ("清蒸鲈鱼", "用清蒸留住鱼肉的鲜嫩，适合忙碌的一天。"),
               ("香菇青菜", "清爽蔬菜搭配鲜香菌菇，十几分钟轻松上桌。"),
               *[(f"家常食谱{i}", "简单的食材，暖心的一餐。") for i in range(4, 15)],
           ], 1)]
STATES = {r["id"]: dict(recipe_id=r["id"], liked=False, favorited=False, like_count=0, favorite_count=0) for r in RECIPES}
VIEWS = []
REQUESTS = []
TOKEN = ".".join(["fixture", base64.urlsafe_b64encode(json.dumps({"exp": time.time()+3600}).encode()).decode().rstrip("="), "not-a-real-token"])
EXPIRED_TOKEN = ".".join(["fixture", base64.urlsafe_b64encode(json.dumps({"exp": 1}).encode()).decode().rstrip("="), "expired-fixture-token"])
CONTROL = {"expire_login": False}
USER = dict(id="fixture-only", tenant_id="fixture-only", email="ui-test@example.invalid", display_name="测试厨房", roles=[])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, data, code=200):
        content = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "http://127.0.0.1:5173"))
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.reply({})

    def handle_request(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        REQUESTS.append(dict(method=self.command, path=path, query=query))
        if path == "/__fixture/control" and self.command == "POST":
            CONTROL.update(body)
            REQUESTS.clear()
            return self.reply({"ok": True})
        if path == "/__fixture/requests":
            return self.reply(REQUESTS)
        if path in ("/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh"):
            if path.endswith("refresh"):
                time.sleep(1)  # Makes concurrent request refresh sharing observable.
            token = EXPIRED_TOKEN if CONTROL["expire_login"] and not path.endswith("refresh") else TOKEN
            return self.reply(dict(access_token=token, refresh_token="fixture-refresh", user=USER))
        if path == "/api/v1/auth/me":
            return self.reply(dict(subject=USER["id"], **USER))
        if path == "/api/v1/auth/logout":
            return self.reply({})
        if path == "/api/v1/chat/sessions":
            return self.reply([])
        if path == "/api/v1/recipes/interactions/query":
            return self.reply(dict(items=[STATES[i] for i in body["recipe_ids"] if i in STATES], missing_recipe_ids=[]))
        offset, limit = int(query.get("offset", [0])[0]), int(query.get("limit", [12])[0])
        if path == "/api/v1/recipes":
            if query.get("name") == ["请求失败"]:
                return self.reply(dict(detail="测试服务暂时不可用"), 503)
            items = [r for r in RECIPES if query.get("name", [""])[0] in r["name"]]
            return self.reply(dict(items=items[offset:offset+limit], total=len(items), has_more=offset+limit<len(items), offset=offset, limit=limit))
        if path == "/api/v1/recipes/favorites":
            items = [dict(recipe_id=r["id"], recipe_name=r["name"], favorited_at="2026-10-09T08:00:00") for r in RECIPES if STATES[r["id"]]["favorited"]]
            return self.reply(dict(items=items[offset:offset+limit], has_more=offset+limit<len(items), offset=offset, limit=limit))
        if path == "/api/v1/recipes/history":
            cursor = int(query.get("cursor", [0])[0])
            items = [dict(recipe_id=i, recipe_name=RECIPES[i-1]["name"], last_viewed_at="2026-10-09T08:00:00Z") for i in VIEWS]
            return self.reply(dict(items=items[cursor:cursor+limit], has_more=cursor+limit<len(items), next_cursor=str(cursor+limit) if cursor+limit<len(items) else None))
        if path == "/api/v1/recipes/rankings":
            popular = query.get("mode", ["today"])[0] == "popular"
            ranked = sorted([(i, s["like_count"]+s["favorite_count"] if popular else int(i in VIEWS)) for i, s in STATES.items()], key=lambda pair: (-pair[1], -pair[0]))
            ranked = [(i, score) for i, score in ranked if score]
            items = [dict(recipe_id=i, recipe_name=RECIPES[i-1]["name"], score=score, rank=n+1) for n, (i, score) in enumerate(ranked)]
            return self.reply(dict(items=items[offset:offset+limit], has_more=offset+limit<len(items), updated_at="2026-10-09T08:00:00Z", truncated=False, source="database"))
        parts = path.split("/")
        if len(parts) >= 5 and parts[4].isdigit():
            recipe_id = int(parts[4])
            if recipe_id not in STATES:
                return self.reply(dict(detail="Recipe not found"), 404)
            if len(parts) == 5:
                recipe = dict(RECIPES[recipe_id-1], ingredients=[dict(ingredient=dict(id=1, name="番茄"), quantity="200", unit="克", preparation="切块"), dict(ingredient=dict(id=2, name="鸡蛋"), quantity="2", unit="个")], steps=[dict(number=1, instruction="食材洗净备好。"), dict(number=2, instruction="加热锅具，炒熟食材后装盘。")], nutrition=dict(calories="320", protein_g="18", carbs_g="20", fat_g="12", basis="per_recipe"))
                return self.reply(recipe)
            kind = parts[5]
            if kind == "view":
                if recipe_id in VIEWS:
                    VIEWS.remove(recipe_id)
                VIEWS.insert(0, recipe_id)
                return self.reply({})
            if kind in ("like", "favorite"):
                state = STATES[recipe_id]
                enabled = self.command == "PUT"
                state["liked" if kind == "like" else "favorited"] = enabled
                state[f"{kind}_count"] = int(enabled)
                return self.reply(state)
        return self.reply(dict(detail="fixture route not supported"), 404)

    do_GET = do_POST = do_PUT = do_DELETE = handle_request


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 18080), Handler).serve_forever()

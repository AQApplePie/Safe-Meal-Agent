# 最终关键架构树

    safemeal/
    ├── agent/
    │   ├── contracts/
    │   ├── understanding/
    │   ├── context/
    │   ├── safety/
    │   ├── gateway/
    │   ├── workflow/                  # 外层控制面
    │   └── runtime/                   # 内层决策循环
    │       ├── orchestration/
    │       ├── model/
    │       ├── memory/
    │       ├── aggregation/
    │       └── tools/
    ├── modules/
    │   ├── recipe/
    │   ├── dietary/
    │   ├── identity/
    │   ├── knowledge/
    │   ├── conversation/
    │   └── interaction/               # 仅 README 边界
    ├── interfaces/http/
    ├── infrastructure/
    ├── bootstrap/composition/
    ├── shared/contracts/
    ├── config/
    └── main.py

旧 safemeal/application/ 与空的 infrastructure/tools/ 已移除，不存在重复实现。

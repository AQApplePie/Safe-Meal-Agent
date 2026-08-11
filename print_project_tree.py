from __future__ import annotations

import argparse
from pathlib import Path


# 默认忽略的目录
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "target",
    "build",
    "dist",
}

# 默认忽略的文件
DEFAULT_IGNORE_FILES = {
    ".DS_Store",
    "Thumbs.db",
}


def should_ignore(
    path: Path,
    output_file: Path | None = None,
) -> bool:
    """判断文件或目录是否应该被忽略。"""

    # 不把生成的目录树 txt 文件写进目录树中
    if output_file is not None:
        try:
            if path.resolve() == output_file.resolve():
                return True
        except OSError:
            pass

    if path.is_dir() and path.name in DEFAULT_IGNORE_DIRS:
        return True

    if path.is_file() and path.name in DEFAULT_IGNORE_FILES:
        return True

    # 忽略 Python 编译文件
    if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}:
        return True

    return False


def get_entries(
    directory: Path,
    show_hidden: bool,
    output_file: Path,
) -> list[Path]:
    """读取目录内容并进行排序。"""

    try:
        entries = []

        for path in directory.iterdir():
            if should_ignore(path, output_file):
                continue

            # 默认不展示隐藏文件
            if not show_hidden and path.name.startswith("."):
                continue

            entries.append(path)

    except PermissionError:
        return []

    # 文件夹在前，文件在后，并按照名称排序
    return sorted(
        entries,
        key=lambda path: (
            not path.is_dir(),
            path.name.lower(),
        ),
    )


def build_tree(
    root: Path,
    output_file: Path,
    max_depth: int | None = None,
    show_hidden: bool = False,
) -> str:
    """扫描项目并生成树形目录字符串。"""

    lines = [f"{root.name}/"]

    def walk(
        current_directory: Path,
        prefix: str,
        current_depth: int,
    ) -> None:
        # 限制扫描深度
        if max_depth is not None and current_depth >= max_depth:
            return

        entries = get_entries(
            directory=current_directory,
            show_hidden=show_hidden,
            output_file=output_file,
        )

        for index, entry in enumerate(entries):
            is_last = index == len(entries) - 1

            branch = "└── " if is_last else "├── "
            child_prefix = prefix + (
                "    " if is_last else "│   "
            )

            display_name = entry.name

            if entry.is_dir():
                display_name += "/"

            lines.append(
                f"{prefix}{branch}{display_name}"
            )

            if entry.is_dir():
                walk(
                    current_directory=entry,
                    prefix=child_prefix,
                    current_depth=current_depth + 1,
                )

    walk(
        current_directory=root,
        prefix="",
        current_depth=0,
    )

    return "\n".join(lines)


def get_output_file(root: Path) -> Path:
    """生成与项目目录同名的 txt 文件路径。

    例如项目目录为：
        D:/projects/big-market

    输出文件为：
        D:/projects/big-market/big-market.txt
    """

    return root / f"{root.name}.txt"


def save_tree(
    tree_text: str,
    output_file: Path,
) -> None:
    """将目录树保存到 txt 文件。"""

    try:
        output_file.write_text(
            tree_text + "\n",
            encoding="utf-8",
        )
    except PermissionError as error:
        raise SystemExit(
            f"没有权限写入文件：{output_file}"
        ) from error
    except OSError as error:
        raise SystemExit(
            f"保存文件失败：{error}"
        ) from error


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "扫描项目目录，在终端输出目录树，"
            "并保存为与项目目录同名的 txt 文件。"
        )
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="需要扫描的目录，默认扫描当前目录。",
    )

    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="最大扫描深度，例如 --max-depth 5。",
    )

    parser.add_argument(
        "--show-hidden",
        action="store_true",
        help="显示 .env、.gitignore 等隐藏文件。",
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    # 获取需要扫描的项目目录
    root = Path(arguments.path).expanduser().resolve()

    if not root.exists():
        raise SystemExit(
            f"错误：指定路径不存在：{root}"
        )

    if not root.is_dir():
        raise SystemExit(
            f"错误：指定路径不是目录：{root}"
        )

    if arguments.max_depth is not None:
        if arguments.max_depth < 1:
            raise SystemExit(
                "错误：--max-depth 必须大于或等于 1。"
            )

    # 自动生成同名 txt 文件路径
    output_file = get_output_file(root)

    # 生成目录树
    tree_text = build_tree(
        root=root,
        output_file=output_file,
        max_depth=arguments.max_depth,
        show_hidden=arguments.show_hidden,
    )

    # 在终端打印
    print(tree_text)

    # 保存到 txt 文件
    save_tree(
        tree_text=tree_text,
        output_file=output_file,
    )

    print()
    print("目录扫描完成。")
    print(f"结果已保存至：{output_file}")


if __name__ == "__main__":
    main()
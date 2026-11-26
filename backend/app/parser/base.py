"""Base extractor utilities, SourceSpan helpers, and URI generators."""
from __future__ import annotations

import re
from typing import Any
from tree_sitter import Node

from app.models.ir import SourceSpan, DependencyCategory

PYTHON_STDLIB = {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "collections",
    "concurrent", "contextlib", "copy", "csv", "dataclasses", "datetime",
    "decimal", "difflib", "dis", "enum", "errno", "functools", "glob",
    "gzip", "hashlib", "heapq", "hmac", "html", "http", "importlib",
    "inspect", "io", "itertools", "json", "logging", "math", "multiprocessing",
    "operator", "os", "pathlib", "pickle", "platform", "queue", "random",
    "re", "secrets", "select", "shutil", "signal", "socket", "sqlite3",
    "ssl", "statistics", "string", "subprocess", "sys", "tempfile", "threading",
    "time", "traceback", "typing", "unittest", "urllib", "uuid", "warnings",
    "weakref", "zipfile", "zlib",
}

NODE_STDLIB = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console",
    "constants", "crypto", "dgram", "diagnostics_channel", "dns", "domain",
    "events", "fs", "fs/promises", "http", "http2", "https", "inspector",
    "module", "net", "os", "path", "path/posix", "path/win32", "perf_hooks",
    "process", "punycode", "querystring", "readline", "repl", "stream",
    "stream/promises", "stream/consumers", "stream/web", "string_decoder",
    "timers", "timers/promises", "tls", "trace_events", "tty", "url", "util",
    "util/types", "v8", "vm", "wasi", "worker_threads", "zlib",
}


def to_source_span(node: Node, source_bytes: bytes | None = None) -> SourceSpan:
    """Convert a Tree-sitter Node's point coordinates to 1-based SourceSpan."""
    start_row, start_col = node.start_point.row, node.start_point.column
    end_row, end_col = node.end_point.row, node.end_point.column

    # Tree-sitter uses UTF-8 byte columns; Monaco uses UTF-16 code units.
    if source_bytes is not None:
        start_prefix = source_bytes[node.start_byte - start_col:node.start_byte]
        end_prefix = source_bytes[node.end_byte - end_col:node.end_byte]
        start_col = len(start_prefix.decode('utf-8').encode('utf-16-le')) // 2
        end_col = len(end_prefix.decode('utf-8').encode('utf-16-le')) // 2

    start_line = start_row + 1
    end_line = end_row + 1

    if end_line < start_line:
        end_line = start_line
    if end_line == start_line and end_col < start_col:
        end_col = start_col

    return SourceSpan(
        start_line=start_line,
        end_line=end_line,
        start_col=start_col,
        end_col=end_col,
    )


def node_text(node: Node, source_bytes: bytes) -> str:
    """Extract decoded utf-8 text from a node."""
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def sanitize_id_part(name: str) -> str:
    """Clean symbol name for URI usage."""
    return re.sub(r"[^a-zA-Z0-9_.]", "_", name)


def make_module_id(file_path: str) -> str:
    cleaned = sanitize_id_part(file_path.replace("/", "_").replace("\\", "_"))
    return f"mod_{cleaned}" if cleaned else "mod_1"


def make_container_id(module_id: str, name: str, line: int) -> str:
    return f"sym:container:{module_id}:{sanitize_id_part(name)}:{line}"


def make_callable_id(module_id: str, qualname: str, line: int) -> str:
    return f"sym:func:{module_id}:{sanitize_id_part(qualname)}:{line}"


def make_variable_id(module_id: str, name: str, line: int) -> str:
    return f"sym:var:{module_id}:{sanitize_id_part(name)}:{line}"


def make_param_id(module_id: str, callable_name: str, name: str) -> str:
    return f"param:{module_id}:{sanitize_id_part(callable_name)}:{sanitize_id_part(name)}"


def make_dep_id(module_id: str, name: str, line: int) -> str:
    return f"dep:{module_id}:{sanitize_id_part(name)}:{line}"


def classify_python_dependency(module_name: str) -> DependencyCategory:
    root_pkg = module_name.split(".")[0]
    if root_pkg in PYTHON_STDLIB:
        return "stdlib"
    if module_name.startswith("."):
        return "internal_module"
    return "third_party"


def classify_js_dependency(module_name: str) -> DependencyCategory:
    if module_name.startswith("node:") or module_name in NODE_STDLIB:
        return "stdlib"
    if module_name.startswith(".") or module_name.startswith("/"):
        return "internal_module"
    return "third_party"

"""Language detection and tree-sitter parser initialization."""
from __future__ import annotations

import os
from typing import Literal
from tree_sitter import Language, Parser
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript
import tree_sitter_go
import tree_sitter_java

try:
    from pygments.lexers import guess_lexer, get_lexer_for_filename
    from pygments.util import ClassNotFound
except ImportError:
    guess_lexer = None
    get_lexer_for_filename = None

SupportedLanguage = Literal["python", "javascript", "typescript", "go", "java"]

EXT_MAP: dict[str, SupportedLanguage] = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
}

PARADIGM_MAP: dict[SupportedLanguage, str] = {
    "python": "multi-paradigm (object-oriented, imperative, functional)",
    "javascript": "multi-paradigm (event-driven, prototype-based, functional)",
    "typescript": "multi-paradigm (statically-typed, object-oriented, functional)",
    "go": "concurrent, imperative, statically-typed",
    "java": "class-based, object-oriented, statically-typed",
}

# Cache compiled Language instances
_LANGUAGES: dict[str, Language] = {
    "python": Language(tree_sitter_python.language()),
    "javascript": Language(tree_sitter_javascript.language()),
    "typescript": Language(tree_sitter_typescript.language_typescript()),
    "tsx": Language(tree_sitter_typescript.language_tsx()),
    "go": Language(tree_sitter_go.language()),
    "java": Language(tree_sitter_java.language()),
}


def detect_language(code: str, filename: str | None = None) -> SupportedLanguage:
    """Detect language from filename extension or code content analysis."""
    if filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext in EXT_MAP:
            return EXT_MAP[ext]

    # Content heuristic checks
    trimmed = code.strip()
    if trimmed.startswith("#!") and "python" in trimmed.split("\n")[0]:
        return "python"

    # Fast heuristics for common syntax markers
    if any(line.startswith("package ") for line in trimmed.splitlines()[:5]):
        return "go"
    if "public class " in code or "public static void main" in code:
        return "java"
    if "def " in code and (":" in code or "import " in code):
        return "python"
    if "interface " in code or ": string" in code or ": number" in code or ": boolean" in code or "type " in code:
        return "typescript"
    if "function " in code or "const " in code or "let " in code or "console.log" in code:
        return "javascript"

    # Pygments fallback
    if guess_lexer is not None:
        try:
            lexer = guess_lexer(code[:2000])
            name = lexer.name.lower()
            if "python" in name:
                return "python"
            if "typescript" in name:
                return "typescript"
            if "javascript" in name:
                return "javascript"
            if "go" in name:
                return "go"
            if "java" in name:
                return "java"
        except Exception:
            pass

    # Default fallback
    return "python"


def get_parser(language: SupportedLanguage | str) -> tuple[Parser, Language]:
    """Get a Tree-sitter Parser and Language instance for the given language."""
    lang_key = language.lower()
    if lang_key not in _LANGUAGES:
        lang_key = "python"
    lang = _LANGUAGES[lang_key]
    parser = Parser(lang)
    return parser, lang


def get_runtime_paradigm(language: str) -> str:
    """Return description of runtime paradigm for the language."""
    return PARADIGM_MAP.get(language.lower(), "imperative/object-oriented")

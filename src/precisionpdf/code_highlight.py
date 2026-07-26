"""Lightweight regex-based syntax highlighting.

Tokenizes source code into colored spans for PDF rendering.
No external dependencies — all patterns are built from the standard
library's `re` module.

Supports: Python, JavaScript, TypeScript, Rust, Go, HTML, CSS, SQL,
JSON, YAML, Shell/Bash. Adding a language requires only a keyword set
and optional comment/string patterns.

Usage:
    tokens = tokenize("def foo(): pass", "python")
    colored = colorize(tokens, "dark_modern")
    # colored is [(text, hex_color), ...]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "Token", "tokenize", "colorize", "THEMES", "LANGUAGES",
]

TokenType = Literal[
    "keyword", "string", "comment", "number", "operator",
    "function", "type", "punctuation", "plain",
]


@dataclass(frozen=True, slots=True)
class Token:
    text: str
    type: TokenType


_KEYWORDS: dict[str, set[str]] = {
    "python": {
        "False", "None", "True", "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del", "elif", "else", "except",
        "finally", "for", "from", "global", "if", "import", "in", "is",
        "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
        "while", "with", "yield",
    },
    "javascript": {
        "async", "await", "break", "case", "catch", "class", "const",
        "continue", "debugger", "default", "delete", "do", "else", "export",
        "extends", "finally", "for", "function", "if", "import", "in",
        "instanceof", "let", "new", "of", "return", "super", "switch",
        "this", "throw", "try", "typeof", "var", "void", "while", "with",
        "yield", "true", "false", "null", "undefined",
    },
    "typescript": {
        "abstract", "any", "as", "async", "await", "boolean", "break",
        "case", "catch", "class", "const", "continue", "debugger", "declare",
        "default", "delete", "do", "else", "enum", "export", "extends",
        "finally", "for", "from", "function", "if", "implements", "import",
        "in", "instanceof", "interface", "keyof", "let", "namespace", "new",
        "never", "of", "private", "protected", "public", "readonly",
        "return", "static", "super", "switch", "this", "throw", "try",
        "type", "typeof", "undefined", "var", "void", "while", "with",
        "yield", "true", "false", "null", "number", "string", "symbol",
    },
    "rust": {
        "as", "async", "await", "break", "const", "continue", "crate",
        "dyn", "else", "enum", "extern", "false", "fn", "for", "if",
        "impl", "in", "let", "loop", "match", "mod", "move", "mut",
        "pub", "ref", "return", "self", "Self", "static", "struct",
        "super", "trait", "true", "type", "unsafe", "use", "where",
        "while",
    },
    "go": {
        "break", "case", "chan", "const", "continue", "default", "defer",
        "else", "fallthrough", "for", "func", "go", "goto", "if", "import",
        "interface", "map", "package", "range", "return", "select", "struct",
        "switch", "type", "var", "true", "false", "nil",
    },
    "sql": {
        "SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE", "CREATE",
        "DROP", "ALTER", "TABLE", "INDEX", "VIEW", "JOIN", "INNER", "LEFT",
        "RIGHT", "OUTER", "ON", "AND", "OR", "NOT", "IN", "IS", "NULL",
        "AS", "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET", "UNION",
        "ALL", "DISTINCT", "INTO", "VALUES", "SET", "BEGIN", "COMMIT",
        "ROLLBACK", "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "CASCADE",
        "EXISTS", "BETWEEN", "LIKE", "COUNT", "SUM", "AVG", "MIN", "MAX",
        "CASE", "WHEN", "THEN", "ELSE", "END", "ASC", "DESC",
        "select", "from", "where", "insert", "update", "delete", "create",
        "drop", "alter", "table", "index", "view", "join", "inner", "left",
        "right", "outer", "on", "and", "or", "not", "in", "is", "null",
        "as", "order", "by", "group", "having", "limit", "offset", "union",
        "all", "distinct", "into", "values", "set", "begin", "commit",
        "rollback", "primary", "key", "foreign", "references", "cascade",
        "exists", "between", "like", "count", "sum", "avg", "min", "max",
        "case", "when", "then", "else", "end", "asc", "desc",
    },
    "shell": {
        "if", "then", "else", "elif", "fi", "for", "while", "do", "done",
        "case", "esac", "in", "function", "return", "exit", "local",
        "export", "source", "alias", "unalias", "set", "unset", "declare",
        "readonly", "shift", "trap", "eval", "exec", "true", "false",
    },
}
_KEYWORDS["bash"] = _KEYWORDS["shell"]
_KEYWORDS["sh"] = _KEYWORDS["shell"]
_KEYWORDS["js"] = _KEYWORDS["javascript"]
_KEYWORDS["ts"] = _KEYWORDS["typescript"]
_KEYWORDS["py"] = _KEYWORDS["python"]

_TYPES: dict[str, set[str]] = {
    "python": {"int", "float", "str", "bool", "list", "dict", "tuple", "set", "bytes", "object", "type"},
    "javascript": {"Array", "Object", "String", "Number", "Boolean", "Map", "Set", "Promise", "Date"},
    "typescript": {"Array", "Object", "String", "Number", "Boolean", "Map", "Set", "Promise", "Date", "Record", "Partial", "Required", "Readonly"},
    "rust": {"i8", "i16", "i32", "i64", "i128", "u8", "u16", "u32", "u64", "u128", "f32", "f64", "bool", "char", "str", "String", "Vec", "Option", "Result", "Box", "Rc", "Arc"},
    "go": {"int", "int8", "int16", "int32", "int64", "uint", "uint8", "uint16", "uint32", "uint64", "float32", "float64", "complex64", "complex128", "byte", "rune", "string", "bool", "error"},
}
_TYPES["ts"] = _TYPES["typescript"]
_TYPES["js"] = _TYPES["javascript"]
_TYPES["py"] = _TYPES["python"]


def _build_pattern(language: str) -> re.Pattern:
    parts: list[str] = []

    if language in ("html", "xml"):
        parts.append(r"(?P<comment><!--[\s\S]*?-->)")
        parts.append(r'(?P<string>"[^"]*"|\'[^\']*\')')
        parts.append(r"(?P<keyword></?[a-zA-Z][a-zA-Z0-9-]*)")
        parts.append(r"(?P<type>[a-zA-Z][a-zA-Z0-9-]*(?==))")
        parts.append(r"(?P<punctuation>[<>=/])")
    elif language == "css":
        parts.append(r"(?P<comment>/\*[\s\S]*?\*/)")
        parts.append(r'(?P<string>"[^"]*"|\'[^\']*\')')
        parts.append(r"(?P<keyword>@[a-zA-Z-]+)")
        parts.append(r"(?P<type>[.#][a-zA-Z_][a-zA-Z0-9_-]*)")
        parts.append(r"(?P<function>[a-zA-Z-]+(?=\s*\())")
        parts.append(r"(?P<number>-?\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|pt|s|ms)?)")
        parts.append(r"(?P<punctuation>[{}():;,])")
    elif language == "json":
        parts.append(r'(?P<string>"(?:[^"\\]|\\.)*"(?=\s*:))')
        parts.append(r'(?P<type>"(?:[^"\\]|\\.)*")')
        parts.append(r"(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
        parts.append(r"(?P<keyword>true|false|null)")
        parts.append(r"(?P<punctuation>[{}\[\]:,])")
    elif language in ("yaml", "yml"):
        parts.append(r"(?P<comment>#[^\n]*)")
        parts.append(r'(?P<string>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')')
        parts.append(r"(?P<keyword>[a-zA-Z_][a-zA-Z0-9_.-]*(?=\s*:))")
        parts.append(r"(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
        parts.append(r"(?P<type>true|false|null|yes|no|on|off)")
        parts.append(r"(?P<punctuation>[-:|>])")
    else:
        if language in ("python", "py"):
            parts.append(r'(?P<string>"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|f"[^"]*"|f\'[^\']*\'|"[^"]*"|\'[^\']*\')')
            parts.append(r"(?P<comment>#[^\n]*)")
        elif language in ("shell", "bash", "sh"):
            parts.append(r'(?P<string>"(?:[^"\\]|\\.)*"|\'[^\']*\'|`[^`]*`)')
            parts.append(r"(?P<comment>#[^\n]*)")
        elif language in ("rust",):
            parts.append(r'(?P<string>"(?:[^"\\]|\\.)*")')
            parts.append(r"(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)")
        elif language == "sql":
            parts.append(r"(?P<string>'(?:[^'\\]|\\.)*')")
            parts.append(r"(?P<comment>--[^\n]*|/\*[\s\S]*?\*/)")
        else:
            parts.append(r'(?P<string>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`)')
            parts.append(r"(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)")

        parts.append(r"(?P<number>0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
        parts.append(r"(?P<function>[a-zA-Z_][a-zA-Z0-9_]*(?=\s*\())")
        parts.append(r"(?P<word>[a-zA-Z_][a-zA-Z0-9_]*)")
        parts.append(r"(?P<operator>[+\-*/%=!<>&|^~?]+|=>|->)")
        parts.append(r"(?P<punctuation>[{}()\[\]:;,.])")

    parts.append(r"(?P<newline>\n)")
    parts.append(r"(?P<space>[ \t]+)")
    parts.append(r"(?P<other>.)")

    return re.compile("|".join(parts))


_pattern_cache: dict[str, re.Pattern] = {}


def _get_pattern(language: str) -> re.Pattern:
    if language not in _pattern_cache:
        _pattern_cache[language] = _build_pattern(language)
    return _pattern_cache[language]


def tokenize(code: str, language: str = "text") -> list[Token]:
    language = language.lower().strip()
    if language in ("text", "plain", ""):
        return [Token(code, "plain")]

    pattern = _get_pattern(language)
    keywords = _KEYWORDS.get(language, set())
    types = _TYPES.get(language, set())
    tokens: list[Token] = []

    for m in pattern.finditer(code):
        kind = m.lastgroup
        text = m.group()

        if kind in ("space", "newline", "other"):
            tokens.append(Token(text, "plain"))
        elif kind == "comment":
            tokens.append(Token(text, "comment"))
        elif kind == "string":
            tokens.append(Token(text, "string"))
        elif kind == "number":
            tokens.append(Token(text, "number"))
        elif kind == "keyword":
            tokens.append(Token(text, "keyword"))
        elif kind == "function":
            if text in keywords:
                tokens.append(Token(text, "keyword"))
            elif text in types:
                tokens.append(Token(text, "type"))
            else:
                tokens.append(Token(text, "function"))
        elif kind == "word":
            if text in keywords:
                tokens.append(Token(text, "keyword"))
            elif text in types:
                tokens.append(Token(text, "type"))
            else:
                tokens.append(Token(text, "plain"))
        elif kind == "type":
            tokens.append(Token(text, "type"))
        elif kind == "operator":
            tokens.append(Token(text, "operator"))
        elif kind == "punctuation":
            tokens.append(Token(text, "punctuation"))
        else:
            tokens.append(Token(text, "plain"))

    return tokens


THEMES: dict[str, dict[TokenType, str]] = {
    "dark_modern": {
        "keyword":     "569cd6",
        "string":      "ce9178",
        "comment":     "6a9955",
        "number":      "b5cea8",
        "operator":    "d4d4d4",
        "function":    "dcdcaa",
        "type":        "4ec9b0",
        "punctuation": "d4d4d4",
        "plain":       "d4d4d4",
    },
    "light_clean": {
        "keyword":     "0000ff",
        "string":      "a31515",
        "comment":     "008000",
        "number":      "098658",
        "operator":    "000000",
        "function":    "795e26",
        "type":        "267f99",
        "punctuation": "000000",
        "plain":       "000000",
    },
    "night_owl": {
        "keyword":     "c792ea",
        "string":      "ecc48d",
        "comment":     "637777",
        "number":      "f78c6c",
        "operator":    "7fdbca",
        "function":    "82aaff",
        "type":        "ffcb6b",
        "punctuation": "7fdbca",
        "plain":       "d6deeb",
    },
}

THEME_BACKGROUNDS: dict[str, str] = {
    "dark_modern": "1e1e1e",
    "light_clean": "ffffff",
    "night_owl":   "011627",
}

LANGUAGES = sorted(set(
    k for k in list(_KEYWORDS.keys()) + ["html", "css", "json", "yaml", "yml", "xml", "text"]
    if k not in ("js", "ts", "py", "sh")
))


def colorize(tokens: list[Token], theme: str = "dark_modern") -> list[tuple[str, str]]:
    colors = THEMES.get(theme, THEMES["dark_modern"])
    return [(t.text, colors.get(t.type, colors["plain"])) for t in tokens]

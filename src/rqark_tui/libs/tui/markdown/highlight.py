import re

from rqark_tui.libs.tui.ansi import _C

# token definitions

# Canonical token order: earlier rules win when two match at the same position.
# So put specific things (keywords) before generic (identifiers).

_PY_KEYWORDS: tuple[str, ...] = (
    'False',
    'None',
    'True',
    'and',
    'as',
    'assert',
    'async',
    'await',
    'break',
    'class',
    'continue',
    'def',
    'del',
    'elif',
    'else',
    'except',
    'finally',
    'for',
    'from',
    'global',
    'if',
    'import',
    'in',
    'is',
    'lambda',
    'nonlocal',
    'not',
    'or',
    'pass',
    'raise',
    'return',
    'try',
    'while',
    'with',
    'yield',
)

_SH_KEYWORDS: tuple[str, ...] = (
    'if',
    'then',
    'else',
    'elif',
    'fi',
    'case',
    'esac',
    'for',
    'while',
    'until',
    'do',
    'done',
    'in',
    'select',
    'function',
    'time',
    'return',
    'exit',
    'export',
    'local',
    'readonly',
    'unset',
    'source',
    'eval',
    'exec',
    'trap',
    'set',
    'shift',
    'continue',
    'break',
)

_RUST_KEYWORDS: tuple[str, ...] = (
    'as',
    'async',
    'await',
    'break',
    'const',
    'continue',
    'crate',
    'dyn',
    'else',
    'enum',
    'extern',
    'false',
    'fn',
    'for',
    'if',
    'impl',
    'in',
    'let',
    'loop',
    'match',
    'mod',
    'move',
    'mut',
    'pub',
    'ref',
    'return',
    'self',
    'Self',
    'static',
    'struct',
    'super',
    'trait',
    'true',
    'type',
    'union',
    'unsafe',
    'use',
    'where',
    'while',
    'yield',
)

_JS_KEYWORDS: tuple[str, ...] = (
    'async',
    'await',
    'break',
    'case',
    'catch',
    'class',
    'const',
    'continue',
    'debugger',
    'default',
    'delete',
    'do',
    'else',
    'export',
    'extends',
    'false',
    'finally',
    'for',
    'function',
    'if',
    'import',
    'in',
    'instanceof',
    'let',
    'new',
    'null',
    'of',
    'return',
    'super',
    'switch',
    'this',
    'throw',
    'true',
    'try',
    'typeof',
    'undefined',
    'var',
    'void',
    'while',
    'with',
    'yield',
)

_SQL_KEYWORDS: tuple[str, ...] = (
    'SELECT',
    'FROM',
    'WHERE',
    'INSERT',
    'UPDATE',
    'DELETE',
    'CREATE',
    'DROP',
    'ALTER',
    'TABLE',
    'INDEX',
    'INTO',
    'VALUES',
    'SET',
    'JOIN',
    'LEFT',
    'RIGHT',
    'INNER',
    'OUTER',
    'ON',
    'AS',
    'AND',
    'OR',
    'NOT',
    'NULL',
    'IS',
    'IN',
    'LIKE',
    'BETWEEN',
    'ORDER',
    'BY',
    'GROUP',
    'HAVING',
    'LIMIT',
    'OFFSET',
    'UNION',
    'ALL',
    'DISTINCT',
    'EXISTS',
    'CASE',
    'WHEN',
    'THEN',
    'ELSE',
    'END',
    'BEGIN',
    'COMMIT',
    'ROLLBACK',
    'PRIMARY',
    'KEY',
    'FOREIGN',
    'REFERENCES',
    'DEFAULT',
    'CHECK',
    'UNIQUE',
    'CASCADE',
)


# language config


class _Lang:
    kw: tuple[str, ...]
    comment: re.Pattern[str] | None = None  # line comment
    string_single: bool = True
    string_double: bool = True
    string_backtick: bool = False
    string_triple: bool = False  # """  '''
    fstring_prefix: bool = False  # f"..."

    def __init__(self, *, name: str, **kwargs: object) -> None:
        self.name = name
        for k, v in kwargs.items():
            setattr(self, k, v)


_LANGS: dict[str, _Lang] = {}


def _reg(*names: str, **kwargs: object) -> _Lang:
    lang = _Lang(name=names[0], **kwargs)
    for n in names:
        _LANGS[n] = lang
    return lang


_py = _reg('python', 'python3', 'py', kw=_PY_KEYWORDS, comment=re.compile(r'#'), string_triple=True, fstring_prefix=True)
_reg('python2', kw=_PY_KEYWORDS, comment=re.compile(r'#'), string_triple=True)

_reg('sh', 'bash', 'zsh', 'shell', kw=_SH_KEYWORDS, comment=re.compile(r'#'))
_reg('rust', 'rs', kw=_RUST_KEYWORDS, comment=re.compile(r'//'), string_single=True, string_double=True)
_reg('javascript', 'js', kw=_JS_KEYWORDS, comment=re.compile(r'//'), string_backtick=True)
_reg('typescript', 'ts', 'tsx', kw=_JS_KEYWORDS, comment=re.compile(r'//'), string_backtick=True)
_reg('sql', kw=_SQL_KEYWORDS, comment=re.compile(r'--'), string_single=True, string_double=False)
_reg('json', kw=(), string_single=False, string_double=True)
_reg('yaml', 'yml', kw=(), comment=re.compile(r'#'))
_reg('toml', kw=(), comment=re.compile(r'#'))
_reg('diff', kw=())
_reg('text', kw=())


# highlight helpers


def _highlight_line(lang: _Lang, line: str) -> str:
    """Return the given line with ANSI colouring."""
    if not line.strip():
        return line

    # diff mode
    if lang.name == 'diff':
        if line.startswith('@@'):
            return f'{_C.CYN}{line}{_C.RST}'
        if line.startswith('+'):
            return f'{_C.GRN}{line}{_C.RST}'
        if line.startswith('-'):
            return f'{_C.DIM}{line}{_C.RST}'
        return line

    # generic fallback
    if not lang.kw and lang.comment is None:
        return line

    result: list[str] = []
    i = 0
    n = len(line)

    while i < n:
        # string matching (triple)
        if lang.string_triple and i + 2 < n and line[i : i + 3] in ('"""', "'''"):
            quote = line[i : i + 3]
            j = line.find(quote, i + 3)
            if j != -1:
                j += 3
                result.append(f'{_C.GRN}{line[i:j]}{_C.RST}')
                i = j
                continue
            else:
                result.append(f'{_C.GRN}{line[i:]}{_C.RST}')
                return ''.join(result)

        # f-string prefix
        if lang.fstring_prefix and i + 4 < n and line[i : i + 2] in ('f"', "f'"):
            quote_char = line[i + 1]
            # skip the f, process as string
            j = i + 2
            while j < n:
                if line[j] == '\\':
                    j += 2
                    continue
                if line[j] == quote_char:
                    j += 1
                    break
                j += 1
            result.append(f'{_C.GRN}{line[i:j]}{_C.RST}')
            i = j
            continue

        # string matching (single char)
        if line[i] in ('"', "'") and ((line[i] == '"' and lang.string_double) or (line[i] == "'" and lang.string_single)):
            quote = line[i]
            j = i + 1
            while j < n:
                if line[j] == '\\':
                    j += 2
                    continue
                if line[j] == quote:
                    j += 1
                    break
                j += 1
            result.append(f'{_C.GRN}{line[i:j]}{_C.RST}')
            i = j
            continue

        # backtick strings (js/ts)
        if lang.string_backtick and line[i] == '`':
            j = i + 1
            # look for unescaped backtick or ${}
            while j < n:
                if line[j] == '\\':
                    j += 2
                    continue
                if line[j] == '`':
                    j += 1
                    break
                j += 1
            result.append(f'{_C.GRN}{line[i:j]}{_C.RST}')
            i = j
            continue

        # comment
        if lang.comment and lang.comment.match(line[i:]):
            result.append(f'{_C.DIM}{line[i:]}{_C.RST}')
            return ''.join(result)

        # decorator
        if lang.name in ('python', 'python3', 'py') and line[i] == '@' and (i == 0 or line[i - 1] == ' '):
            m = re.match(r'@[\w.]+', line[i:])
            if m:
                result.append(f'{_C.GRY}{m.group()}{_C.RST}')
                i += len(m.group())
                continue

        # number
        m = re.match(r'0[bB][01_]+|0[oO][0-7_]+|0[xX][0-9a-fA-F_]+|\d[\d_]*\.?[\d_]*[eE]?[\+\-]?\d*', line[i:])
        if m:
            result.append(f'{_C.MAG}{m.group()}{_C.RST}')
            i += len(m.group())
            continue

        # word (identifier / keyword)
        m = re.match(r'[\w_]+', line[i:])
        if m:
            word = m.group()
            if word in lang.kw:
                result.append(f'{_C.CYN}{word}{_C.RST}')
            elif word == 'self' and lang.name in ('python', 'python3', 'py'):
                result.append(f'{_C.GRY}{word}{_C.RST}')
            # builtins for python
            elif lang.name in ('python', 'python3', 'py') and word in (
                'int',
                'str',
                'float',
                'bool',
                'list',
                'dict',
                'tuple',
                'set',
                'frozenset',
                'bytes',
                'bytearray',
                'object',
                'type',
                'len',
                'range',
                'enumerate',
                'zip',
                'map',
                'filter',
                'iter',
                'next',
                'print',
                'input',
                'open',
                'isinstance',
                'issubclass',
                'hasattr',
                'getattr',
                'setattr',
                'delattr',
                'id',
                'dir',
                'super',
                'any',
                'all',
                'sorted',
                'reversed',
                'min',
                'max',
                'sum',
                'abs',
                'round',
                'divmod',
                'pow',
                'chr',
                'ord',
                'hex',
                'oct',
                'bin',
                'repr',
                'eval',
                'compile',
                'exec',
                'Exception',
                'ValueError',
                'TypeError',
                'KeyError',
                'RuntimeError',
                'StopIteration',
                'AttributeError',
                'NotImplementedError',
                'ImportError',
                '__init__',
                '__name__',
                '__main__',
                '__file__',
                '__all__',
                '__str__',
                '__repr__',
                '__dict__',
                '__class__',
            ):
                result.append(f'{_C.BLU}{word}{_C.RST}')
            else:
                result.append(word)
            i += len(word)
            continue

        # operator / punctuation
        result.append(line[i])
        i += 1

    return ''.join(result)


# public API


def highlight(code: str, lang: str = '') -> str:
    """Syntax-highlight *code* using ANSI escape sequences.

    *lang*: language identifier (python, sh, rust, js, ts, sql, json, …).
    """
    lang_obj = _LANGS.get(lang.lower()) if lang else _LANGS['text']
    if lang_obj is None:
        lang_obj = _LANGS['text']

    lines = code.split('\n')
    out: list[str] = []
    for line in lines:
        out.append(_highlight_line(lang_obj, line))
    return '\n'.join(out)

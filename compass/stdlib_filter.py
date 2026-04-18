"""stdlib_filter — NET-023 complement: detectar módulos stdlib de Python.

Extraído de `compass/outbound_resolver.py` (REF-033 sub-split). Mantiene
el set fallback + precedencia `sys.stdlib_module_names` (3.10+) sin
ensuciar el archivo del clasificador.

NET-023 promueve imports Python no-resueltos a [EXTERNAL:<head>]. Sin
filtro, módulos stdlib (`os`, `sys`, `json`, `re`, `pathlib`, etc.)
aparecen como nodos externos y ensucian el grafo con ruido que nunca
es una dependencia real del proyecto.

Config flag top-level `external_include_stdlib` (default False):
  - False → stdlib filtrada (comportamiento default post-filtro).
  - True  → stdlib vuelve a aparecer (parity con pre-filtro NET-023).

El set fallback cubre ~280 módulos top-level de Python 3.8. Fuente:
docs Python 3.8 (`docs.python.org/3.8/py-modindex.html`) + ajustes por
módulos removidos en 3.9/3.10 pero presentes en 3.8 (formatter, parser,
symbol, imp, binhex) — los dejamos para que `pathlib.head` matchee en
entornos 3.8/3.9 exactos.
"""

import sys


_PYTHON_STDLIB_FALLBACK = frozenset({
    "__future__", "__main__", "_thread", "abc", "aifc", "antigravity",
    "argparse", "array", "ast", "asynchat", "asyncio", "asyncore", "atexit",
    "audioop", "base64", "bdb", "binascii", "binhex", "bisect", "builtins",
    "bz2", "cProfile", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd",
    "code", "codecs", "codeop", "collections", "colorsys", "compileall",
    "concurrent", "configparser", "contextlib", "contextvars", "copy",
    "copyreg", "crypt", "csv", "ctypes", "curses", "dataclasses", "datetime",
    "dbm", "decimal", "difflib", "dis", "distutils", "doctest", "email",
    "encodings", "ensurepip", "enum", "errno", "faulthandler", "fcntl",
    "filecmp", "fileinput", "fnmatch", "formatter", "fractions", "ftplib",
    "functools", "gc", "genericpath", "getopt", "getpass", "gettext", "glob",
    "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "keyword", "lib2to3", "linecache",
    "locale", "logging", "lzma", "macpath", "mailbox", "mailcap", "marshal",
    "math", "mimetypes", "mmap", "modulefinder", "msilib", "msvcrt",
    "multiprocessing", "netrc", "nis", "nntplib", "ntpath", "numbers",
    "opcode", "operator", "optparse", "os", "ossaudiodev", "parser", "pathlib",
    "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform", "plistlib",
    "poplib", "posix", "posixpath", "pprint", "profile", "pstats", "pty",
    "pwd", "py_compile", "pyclbr", "pydoc", "pydoc_data", "pyexpat", "queue",
    "quopri", "random", "re", "readline", "reprlib", "resource", "rlcompleter",
    "runpy", "sched", "secrets", "select", "selectors", "shelve", "shlex",
    "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr", "socket",
    "socketserver", "spwd", "sqlite3", "sre_compile", "sre_constants",
    "sre_parse", "ssl", "stat", "statistics", "string", "stringprep",
    "struct", "subprocess", "sunau", "symbol", "symtable", "sys", "sysconfig",
    "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile", "termios",
    "test", "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty",
    "turtle", "turtledemo", "types", "typing", "unicodedata", "unittest",
    "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
    "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc",
    "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
})


def is_python_stdlib(module_head):
    """NET-023 complement — True si `module_head` es un módulo stdlib de Python.

    Precedencia:
      - Python 3.10+: `sys.stdlib_module_names` (frozenset oficial del CPython
        que corresponde a la versión del intérprete activo).
      - Python 3.8/3.9: fallback estático `_PYTHON_STDLIB_FALLBACK`.

    `module_head` es el primer segmento del import (ej. para `os.path`,
    head = `os`; para `urllib.request`, head = `urllib`).
    """
    if not module_head:
        return False
    stdlib_names = getattr(sys, "stdlib_module_names", None)
    if stdlib_names is not None:
        return module_head in stdlib_names
    return module_head in _PYTHON_STDLIB_FALLBACK
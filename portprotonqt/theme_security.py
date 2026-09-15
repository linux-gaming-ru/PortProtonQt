"""
Theme security module for PortProtonQt.
Provides security checks for theme files based on actual theme patterns.
"""
import ast
import os
import re
from portprotonqt.logger import get_logger


logger = get_logger(__name__)
MAX_THEME_PY_FILE_SIZE = 512 * 1024
MAX_AST_NODES = 20000
MAX_SOUND_FILE_SIZE = 20 * 1024 * 1024


class ThemeSecurityChecker:
    """
    Allowlist-based security checker for theme files.
    Only constructs observed in real themes are permitted.
    """

    # Absolute imports allowed for all themes
    SAFE_ABSOLUTE_IMPORTS = {
        "portprotonqt.theme_manager",
        "portprotonqt.config",
    }

    # Dangerous method names that must not appear as attribute access.
    # Covers OS/process execution, network calls, and serialization methods
    # commonly used for payload hiding.
    FORBIDDEN_METHODS = frozenset({
        # OS / process execution
        "system", "popen", "execv", "execve", "execl", "execle", "execlp",
        "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve",
        "spawnvp", "spawnvpe", "startfile",
        "run", "check_call", "check_output", "Popen",
        # Network
        "urlopen", "Request", "post", "put", "delete", "patch",
        "ClientSession", "HTTPConnection", "HTTPSConnection",
        # Encoding / decoding
        "b64decode", "b64encode", "fromhex",
        # Serialization
        "loads", "load", "dumps", "dump",
    })

    # Suspicious string patterns in f-strings / string constants (regex)
    SUSPICIOUS_STRING_PATTERNS = [
        (re.compile(r"discord(app)?\.com/api/webhooks/"), "Discord webhook URL"),
        (re.compile(r"(pastebin\.com|paste\.ee|hastebin\.com|ptpb\.pw|ix\.io|dpaste\.com|ghostbin\.com|rentry\.co|termbin\.com)"), "Paste service URL"),
        (re.compile(r"(bit\.ly|tinyurl\.com|t\.co|is\.gd|v\.gd|short\.io)/"), "URL shortener"),
        (re.compile(r"(ngrok\.io|serveo\.net|localtunnel\.me|localhost\.run)/"), "Tunnel service URL"),
        (re.compile(r"(duckdns\.org|no-ip\.com|ddns\.net|dynu\.com)/"), "Dynamic DNS URL"),
        (re.compile(r"(xmrig|cpuminer|minerd|ethminer|stratum\+[a-z]+://)"), "Cryptocurrency miner"),
        (re.compile(r"(pool\.minergate|nanopool\.org|2miners\.com|f2pool\.com|ethermine\.org|nicehash\.com)"), "Mining pool"),
        (re.compile(r"(4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}|\bbc1[a-zA-HJ-NP-Z0-9]{39,59}|0x[0-9a-fA-F]{40})"), "Crypto wallet address"),
        (re.compile(r"(\.mozilla|\.config/chromium|\.config/google-chrome|\.config/BraveSoftware)/"), "Browser profile access"),
        (re.compile(r"~/\.ssh/|/home/[^/]+/\.ssh/"), "SSH key access"),
        (re.compile(r"~/\.gnupg/|/home/[^/]+/\.gnupg/"), "GPG keyring access"),
        (re.compile(r"/etc/(passwd|shadow)"), "System password file access"),
        (re.compile(r"(>>?\s*~/\.(bashrc|zshrc|profile|bash_profile))"), "Shell profile modification"),
        (re.compile(r"(systemctl\s+enable|crontab|/etc/cron\.d/)"), "Persistence mechanism"),
        (re.compile(r"LD_PRELOAD\s*="), "LD_PRELOAD injection"),
    ]

    # Forbidden names that must never appear as identifiers
    # Forbidden names that must never appear as identifiers.
    # Theme files are a restricted style-description language, not full Python.
    # Encoding/decoding/deserialization modules are blocked because they are
    # commonly used for payload hiding and obfuscation. False positives are
    # acceptable — blocking a malicious theme outweighs supporting edge-case
    # theme patterns.
    FORBIDDEN_NAMES = frozenset({
        # Code execution
        "exec", "eval", "compile", "__import__", "open",
        # Introspection / reflection
        "getattr", "setattr", "hasattr", "delattr",
        "globals", "locals", "vars", "dir", "type", "id",
        "object", "issubclass", "isinstance", "callable",
        # Obfuscation / payload encoding
        "json", "orjson", "codecs", "binascii", "struct", "array", "base64",
        # Dangerous deserialization
        "pickle", "marshal", "shelve", "yaml",
        # Dynamic loading
        "importlib", "pkgutil", "zipimport", "runpy",
        "compileall", "py_compile", "code", "codeop",
        # Config parsing (can load arbitrary data)
        "configparser",
        # System / process
        "os", "sys", "subprocess", "shutil", "pathlib",
        "ctypes", "cffi", "signal", "multiprocessing",
        "threading", "asyncio", "posix", "nt",
        # Networking
        "socket", "http", "ftplib", "smtplib", "poplib",
        "imaplib", "telnetlib", "xmlrpc", "webbrowser", "ssl",
        "uuid", "ipaddress",
        # Crypto / hashing
        "hashlib", "hmac", "secrets", "crypt",
        # Database
        "sqlite3",
        # External HTTP
        "requests", "aiohttp",
        # Legacy / compat
        "breakpoint", "quit", "exit", "copyright", "credits", "license", "help",
        "apply", "buffer", "coerce", "intern", "long", "unichr",
        "unicode", "xrange", "cmp", "reload", "basestring",
    })

    # Dunder attributes blocked in all theme code
    FORBIDDEN_DUNDER_ATTRS = frozenset({
        "__class__", "__dict__", "__module__", "__subclasses__", "__bases__",
        "__mro__", "__call__", "__func__", "__self__", "__code__", "__closure__",
        "__globals__", "__name__", "__file__", "__path__", "__package__",
        "__loader__", "__spec__", "__builtins__", "__import__", "__new__",
        "__init__", "__del__", "__repr__", "__str__", "__bytes__", "__format__",
        "__lt__", "__le__", "__eq__", "__ne__", "__gt__", "__ge__", "__hash__",
        "__bool__", "__dir__", "__delattr__", "__getattribute__",
        "__setattr__", "__delete__", "__set__", "__get__", "__set_name__",
        "__prepare__", "__init_subclass__", "__instancecheck__",
        "__subclasscheck__", "__subclasshook__", "__class_getitem__",
        "__annotations__", "__weakref__",
    })

    def __init__(self) -> None:
        self.has_errors = False
        self.errors: list[str] = []
        self._parent_map: dict[int, ast.AST] = {}

    def _add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.has_errors = True

    def check_theme_safety(
        self, theme_file: str, allow_absolute_imports: bool = True,
    ) -> tuple[bool, list[str]]:
        """Check if a single theme Python file is safe. Returns (is_safe, errors)."""
        self.has_errors = False
        self.errors = []
        self._parent_map = {}

        try:
            self._check_file_size(theme_file)
            if self.has_errors:
                return False, self.errors

            content = self._read_file(theme_file)
            if content is None:
                return False, self.errors

            tree = self._parse_file(content, theme_file)
            if tree is None:
                return False, self.errors

            self._build_parent_map(tree)
            self._check_ast_size(tree, theme_file)
            if self.has_errors:
                return False, self.errors

            self._check_top_level(tree, theme_file, allow_absolute_imports)
            self._check_disabled_card_shadow(tree, theme_file)
            self._check_forbidden_patterns(tree, theme_file)

        except Exception as e:
            self._add_error(f"Failed to check theme safety for {theme_file}: {e}")

        return not self.has_errors, self.errors

    def _check_file_size(self, theme_file: str) -> None:
        try:
            size = os.path.getsize(theme_file)
        except OSError as e:
            self._add_error(f"Failed to read theme file size for {theme_file}: {e}")
            return
        if size > MAX_THEME_PY_FILE_SIZE:
            self._add_error(
                f"Theme file {theme_file} is too large ({size} bytes)"
            )

    def _read_file(self, theme_file: str) -> str | None:
        try:
            with open(theme_file, encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            self._add_error(f"Failed to read theme file {theme_file}: {e}")
            return None

    def _parse_file(self, content: str, theme_file: str) -> ast.Module | None:
        try:
            return ast.parse(content)
        except SyntaxError as e:
            self._add_error(f"Syntax error in file {theme_file}: {e}")
            return None

    def _build_parent_map(self, tree: ast.Module) -> None:
        """Build a mapping from child node id to parent node in one pass."""
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self._parent_map[id(child)] = parent

    def _get_parent(self, node: ast.AST) -> ast.AST | None:
        return self._parent_map.get(id(node))

    def _check_ast_size(self, tree: ast.Module, theme_file: str) -> None:
        """Reject files with excessively large AST to prevent DoS."""
        count = sum(1 for _ in ast.walk(tree))
        if count > MAX_AST_NODES:
            self._add_error(
                f"Theme file {theme_file} has too many AST nodes ({count})"
            )

    def _check_top_level(
        self, tree: ast.Module, theme_file: str, allow_absolute_imports: bool,
    ) -> None:
        """Validate top-level module statements against allowlist."""
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._check_import(node, theme_file, allow_absolute_imports)
                continue

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function_def(node, theme_file)
                continue

            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                self._check_assignment(node, theme_file)
                continue

            if isinstance(node, ast.Expr):
                is_docstring = (
                    isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                )
                if not is_docstring:
                    self._add_error(
                        f"Top-level executable expression is forbidden in file {theme_file}"
                    )
                continue

            self._add_error(
                f"Top-level {type(node).__name__} is forbidden in file {theme_file}"
            )

    def _check_disabled_card_shadow(
        self, tree: ast.Module, theme_file: str,
    ) -> None:
        """Reject the card shadow combination that breaks Qt painting."""
        values = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id not in {
                "color_shadow_card", "shadow_blur_radius", "shadow_offset",
            }:
                continue
            try:
                values[target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
        if values == {
            "color_shadow_card": "#00000000",
            "shadow_blur_radius": 0,
            "shadow_offset": (0, 0),
        }:
            self._add_error(
                f"Disabled card shadow breaks Qt painting in file {theme_file}"
            )

    def _check_import(
        self, node: ast.Import | ast.ImportFrom, theme_file: str,
        allow_absolute_imports: bool,
    ) -> None:
        """Validate import node against allowlist."""
        if isinstance(node, ast.ImportFrom):
            if node.level > 0:
                return
            module = node.module or ""
            if module in self.SAFE_ABSOLUTE_IMPORTS or any(
                module.startswith(safe + ".")
                for safe in self.SAFE_ABSOLUTE_IMPORTS
            ):
                return
            if not allow_absolute_imports:
                self._add_error(
                    f"Forbidden import '{module}' in file {theme_file}"
                )
            return

        for alias in node.names:
            if alias.name in self.SAFE_ABSOLUTE_IMPORTS or any(
                alias.name.startswith(safe + ".")
                for safe in self.SAFE_ABSOLUTE_IMPORTS
            ):
                continue
            if not allow_absolute_imports:
                self._add_error(
                    f"Forbidden import '{alias.name}' in file {theme_file}"
                )

    def _check_function_def(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, theme_file: str,
    ) -> None:
        """Validate function definition and its body."""
        if node.decorator_list:
            self._add_error(
                f"Decorators are forbidden in file {theme_file}"
            )

        if node.args.defaults or node.args.kw_defaults:
            has_call = any(
                isinstance(d, ast.Call)
                for d in node.args.defaults
                if d is not None
            ) or any(
                isinstance(d, ast.Call)
                for d in node.args.kw_defaults
                if d is not None
            )
            if has_call:
                self._add_error(
                    f"Function default arguments with calls are forbidden in file {theme_file}"
                )

        self._check_body(node.body, theme_file, "function")

    def _check_body(
        self, body: list[ast.stmt], theme_file: str, context: str,
    ) -> None:
        """Validate statements inside a function body."""
        for stmt in body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                self._check_assignment(stmt, theme_file)
            elif isinstance(stmt, ast.Return):
                if stmt.value is not None:
                    self._check_expression(stmt.value, theme_file, context)
            elif isinstance(stmt, ast.Expr):
                self._check_expression(stmt.value, theme_file, context)
            elif isinstance(stmt, ast.If):
                self._check_body(stmt.body, theme_file, context)
                self._check_body(stmt.orelse, theme_file, context)
            elif isinstance(stmt, ast.Raise):
                pass
            elif isinstance(stmt, ast.Pass):
                pass
            else:
                self._add_error(
                    f"Forbidden {type(stmt).__name__} inside {context} in file {theme_file}"
                )

    def _check_assignment(
        self, node: ast.Assign | ast.AnnAssign, theme_file: str,
    ) -> None:
        """Validate assignment value is a safe expression."""
        if node.value is not None:
            self._check_expression(node.value, theme_file, "assignment")

    def _check_expression(
        self, node: ast.expr, theme_file: str, context: str,
    ) -> None:
        """Validate an expression node is safe."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                self._check_string_literal(node.value, theme_file)
            return
        if isinstance(node, ast.Name):
            if node.id in self.FORBIDDEN_NAMES:
                self._add_error(
                    f"Forbidden name '{node.id}' in {context} in file {theme_file}"
                )
            return
        if isinstance(node, ast.Attribute):
            if node.attr in self.FORBIDDEN_DUNDER_ATTRS:
                self._add_error(
                    f"Forbidden dunder attribute '{node.attr}' in {context} in file {theme_file}"
                )
            self._check_expression(node.value, theme_file, context)
            return
        if isinstance(node, ast.Subscript):
            self._check_expression(node.value, theme_file, context)
            if self._is_builtins_access(node):
                self._add_error(
                    f"__builtins__ access is forbidden in {context} in file {theme_file}"
                )
            return
        if isinstance(node, ast.Call):
            self._check_call(node, theme_file, context)
            return
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if key is not None:
                    self._check_expression(key, theme_file, context)
            for val in node.values:
                self._check_expression(val, theme_file, context)
            return
        if isinstance(node, (ast.List, ast.Tuple)):
            for elt in node.elts:
                self._check_expression(elt, theme_file, context)
            return
        if isinstance(node, ast.Set):
            for elt in node.elts:
                self._check_expression(elt, theme_file, context)
            return
        if isinstance(node, ast.BinOp):
            self._check_expression(node.left, theme_file, context)
            self._check_expression(node.right, theme_file, context)
            return
        if isinstance(node, ast.UnaryOp):
            self._check_expression(node.operand, theme_file, context)
            return
        if isinstance(node, ast.BoolOp):
            for val in node.values:
                self._check_expression(val, theme_file, context)
            return
        if isinstance(node, ast.IfExp):
            self._check_expression(node.test, theme_file, context)
            self._check_expression(node.body, theme_file, context)
            self._check_expression(node.orelse, theme_file, context)
            return
        if isinstance(node, ast.JoinedStr):
            for val in node.values:
                self._check_expression(val, theme_file, context)
            return
        if isinstance(node, ast.FormattedValue):
            self._check_expression(node.value, theme_file, context)
            return
        if isinstance(node, ast.NamedExpr):
            self._check_expression(node.value, theme_file, context)
            return

        self._add_error(
            f"Forbidden expression type {type(node).__name__} in {context} in file {theme_file}"
        )

    def _check_string_literal(self, value: str, theme_file: str) -> None:
        """Check string constants for suspicious patterns."""
        for pattern, desc in self.SUSPICIOUS_STRING_PATTERNS:
            if pattern.search(value):
                self._add_error(
                    f"Suspicious string '{desc}' in file {theme_file}"
                )

    def _check_call(
        self, node: ast.Call, theme_file: str, context: str,
    ) -> None:
        """Validate a function/method call."""
        func = node.func

        if isinstance(func, ast.Name):
            if func.id in self.FORBIDDEN_NAMES:
                self._add_error(
                    f"Forbidden call '{func.id}()' in {context} in file {theme_file}"
                )
            return

        if isinstance(func, ast.Attribute):
            attr = func.attr
            if attr in self.FORBIDDEN_DUNDER_ATTRS:
                self._add_error(
                    f"Forbidden dunder call '{attr}' in {context} in file {theme_file}"
                )
            if attr in self.FORBIDDEN_METHODS:
                self._add_error(
                    f"Forbidden method call '.{attr}()' in {context} in file {theme_file}"
                )
            self._check_expression(func.value, theme_file, context)
            for arg in node.args:
                self._check_expression(arg, theme_file, context)
            for kw in node.keywords:
                self._check_expression(kw.value, theme_file, context)
            return

        if isinstance(func, ast.Subscript):
            self._check_expression(func.value, theme_file, context)
            if self._is_builtins_access(func):
                self._add_error(
                    f"__builtins__ call is forbidden in {context} in file {theme_file}"
                )
            return

        self._add_error(
            f"Forbidden call expression in {context} in file {theme_file}"
        )

    def _check_forbidden_patterns(self, tree: ast.Module, theme_file: str) -> None:
        """Walk AST for structural patterns forbidden in theme code."""
        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                self._add_error(
                    f"While loop is forbidden in file {theme_file}"
                )
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self._add_error(
                    f"For loop is forbidden in file {theme_file}"
                )
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                self._add_error(
                    f"With statement is forbidden in file {theme_file}"
                )
            elif isinstance(node, ast.Try):
                self._add_error(
                    f"Try/except is forbidden in file {theme_file}"
                )
            elif isinstance(node, ast.ClassDef):
                self._add_error(
                    f"Class definition is forbidden in file {theme_file}"
                )
            elif isinstance(node, ast.Lambda):
                self._add_error(
                    f"Lambda is forbidden in file {theme_file}"
                )
            elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                self._add_error(
                    f"Comprehension is forbidden in file {theme_file}"
                )
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                self._add_error(
                    f"Global/nonlocal is forbidden in file {theme_file}"
                )
            elif isinstance(node, (ast.Yield, ast.YieldFrom, ast.Await)):
                self._add_error(
                    f"Yield/await is forbidden in file {theme_file}"
                )
            elif isinstance(node, ast.Raise):
                self._add_error(
                    f"Raise statement is forbidden in file {theme_file}"
                )
            elif isinstance(node, ast.Assert):
                self._add_error(
                    f"Assert is forbidden in file {theme_file}"
                )
            elif isinstance(node, ast.Delete):
                self._add_error(
                    f"Del is forbidden in file {theme_file}"
                )

    def _is_builtins_access(self, node: ast.Subscript) -> bool:
        """Detect __builtins__['...'] style access."""
        target = node.value
        if isinstance(target, ast.Name):
            return target.id == "__builtins__"
        if isinstance(target, ast.Attribute):
            return target.attr == "__builtins__"
        return False


def check_theme_safety(theme_file: str, allow_absolute_imports: bool = True) -> bool:
    """
    Convenience function to check theme safety.
    Returns True if the theme is safe, False otherwise.
    """
    checker = ThemeSecurityChecker()
    is_safe, errors = checker.check_theme_safety(theme_file, allow_absolute_imports)

    for error in errors:
        logger.error(error)

    return is_safe


def check_theme_directory_safety(theme_dir: str, allow_absolute_imports: bool = True) -> bool:
    """Check all files in theme directory for safety."""
    if not os.path.isdir(theme_dir):
        logger.error("Theme directory does not exist: %s", theme_dir)
        return False
    if os.path.islink(theme_dir):
        logger.error("Theme directory symlink is not allowed: %s", theme_dir)
        return False

    theme_root = os.path.realpath(theme_dir)
    prefix = theme_root + os.sep

    for root, dirs, files in os.walk(theme_dir):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            if os.path.islink(dir_path):
                logger.error("Symlinked directory is not allowed in theme: %s", dir_path)
                return False
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for filename in files:
            file_path = os.path.join(root, filename)
            real_path = os.path.realpath(file_path)
            if real_path != theme_root and not real_path.startswith(prefix):
                logger.error("Theme file outside theme directory blocked: %s", file_path)
                return False

            if os.path.islink(file_path):
                logger.error("Symlinked file is not allowed in theme: %s", file_path)
                return False

            if filename.endswith(".py"):
                if not check_theme_safety(file_path, allow_absolute_imports):
                    return False
            elif filename.endswith((".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".jxl")):
                if not is_safe_image_file(file_path):
                    return False
            elif filename.endswith((".ttf", ".otf")):
                if not is_safe_font_file(file_path):
                    return False
            elif filename.lower().endswith(".wav"):
                if not is_safe_sound_file(file_path):
                    return False

    return True


def is_safe_font_file(file_path: str) -> bool:
    """Check if a font file is safe to load."""
    safe_extensions = {".ttf", ".otf"}
    _, ext = os.path.splitext(file_path.lower())
    if ext not in safe_extensions:
        logger.error("Unsafe font file extension for %s: %s", file_path, ext)
        return False

    try:
        file_size = os.path.getsize(file_path)
        if file_size > 10 * 1024 * 1024:
            logger.error("Font file too large (%s bytes): %s", file_size, file_path)
            return False
    except OSError:
        logger.error("Could not get font size for %s", file_path)
        return False

    try:
        with open(file_path, "rb") as f:
            header = f.read(12)
        if (
            not header.startswith(b"\x00\x01\x00\x00")
            and not header.startswith(b"OTTO")
            and not header.startswith(b"true")
            and not header.startswith(b"ttcf")
        ):
            logger.error("Font file %s has invalid signature", file_path)
            return False
    except OSError as e:
        logger.error("Error checking font file signature for %s: %s", file_path, e)
        return False

    return True


def is_safe_sound_file(file_path: str) -> bool:
    """Check a theme sound extension, size, and file signature."""
    _, ext = os.path.splitext(file_path.lower())
    if ext != ".wav":
        logger.error("Unsafe sound file extension for %s: %s", file_path, ext)
        return False
    try:
        file_size = os.path.getsize(file_path)
        if file_size > MAX_SOUND_FILE_SIZE:
            logger.error("Sound file too large (%s bytes): %s", file_size, file_path)
            return False
        with open(file_path, "rb") as sound_file:
            header = sound_file.read(16)
    except OSError as e:
        logger.error("Error reading sound file %s: %s", file_path, e)
        return False

    is_valid = False
    if ext == ".wav":
        is_valid = header.startswith(b"RIFF") and header[8:12] == b"WAVE"
    if not is_valid:
        logger.error("Sound file %s has invalid signature", file_path)
    return is_valid


def is_safe_image_file(file_path: str) -> bool:
    """
    Check if an image file is safe to load by verifying its extension and basic file properties.
    This helps prevent loading malicious files that might be disguised as images.
    """

    # Check file extension first
    safe_extensions = {'.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp', '.jxl'}
    _, ext = os.path.splitext(file_path.lower())

    if ext not in safe_extensions:
        logger.error(f"Unsafe image file extension for {file_path}: {ext}")
        return False

    # Check file size (prevent loading extremely large files)
    try:
        file_size = os.path.getsize(file_path)
        if file_size > 20 * 1024 * 1024:
            logger.error(f"Image file too large ({file_size} bytes): {file_path}")
            return False
        if ext == ".svg" and file_size > 2 * 1024 * 1024:
            logger.error(f"SVG file too large ({file_size} bytes): {file_path}")
            return False
    except OSError:
        logger.error(f"Could not get file size for {file_path}")
        return False

    # For security, we can also check the file's magic bytes (first few bytes)
    # to ensure it's actually an image file and not a disguised executable
    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)  # Read first 32 bytes

        # Check for common image file signatures (magic bytes)
        if ext == '.png':
            # PNG signature: 89 50 4E 47 0D 0A 1A 0A
            if not header.startswith(b'\x89PNG\r\n\x1a\n'):
                logger.error(f"File {file_path} does not have PNG signature")
                return False
        elif ext in ['.jpg', '.jpeg']:
            # JPEG signature: FF D8 FF
            if not header.startswith(b'\xff\xd8\xff'):
                logger.error(f"File {file_path} does not have JPEG signature")
                return False
        elif ext == '.gif':
            # GIF signature: 47 49 46 38 (GIF8)
            if not header.startswith(b'GIF8'):
                logger.error(f"File {file_path} does not have GIF signature")
                return False
        elif ext == '.webp':
            if not (header.startswith(b'RIFF') and header[8:12] == b'WEBP'):
                logger.error(f"File {file_path} does not have WebP signature")
                return False
        elif ext == '.jxl':
            if not (header.startswith(b'\xff\x0a') or header.startswith(b'\x00\x00\x00\x0cJXL ')):
                logger.error(f"File {file_path} does not have JPEG XL signature")
                return False
        # SVG is text-based, so we just check if it contains XML-like structure
        elif ext == '.svg':
            try:
                with open(file_path, 'rb') as f:
                    svg_bytes = f.read()
                header_str = svg_bytes.decode('utf-8', errors='ignore')
                lower_svg = header_str.lower()
                # Basic check for SVG XML structure
                if not ('<svg' in lower_svg or '<?xml' in lower_svg):
                    logger.error(f"File {file_path} does not appear to be a valid SVG")
                    return False
                if (
                    "<script" in lower_svg
                    or "foreignobject" in lower_svg
                    or "<!entity" in lower_svg
                    or "<image" in lower_svg
                    or "<use" in lower_svg
                    or "@import" in lower_svg
                    or "onload=" in lower_svg
                    or "onclick=" in lower_svg
                    or "onmouseover=" in lower_svg
                    or "onerror=" in lower_svg
                    or "javascript:" in lower_svg
                    or "data:" in lower_svg
                    or "xlink:href=\"http" in lower_svg
                    or "href=\"http" in lower_svg
                    or "xlink:href='http" in lower_svg
                    or "href='http" in lower_svg
                    or "file://" in lower_svg
                ):
                    logger.warning(f"SVG file contains unsafe content: {file_path}")
                    return False
            except UnicodeDecodeError:
                logger.warning(f"SVG file {file_path} contains invalid UTF-8")
                return False
    except Exception as e:
        logger.error(f"Error checking image file signature for {file_path}: {e}")
        return False

    return True

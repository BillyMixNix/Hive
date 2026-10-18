from pathlib import Path
import ast


DEFAULT_SKIP_FILES = {
    "__init__.py",
}

DEFAULT_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "backups",
    "results",
}


class RepoMap:
    """
    Lightweight repository awareness for Hive.

    Tracks:
    - known python files
    - symbol -> file
    - file -> symbols
    - import graph (file -> imported files)
    - reverse import graph (file <- importer files)
    - symbol reference graph (symbol -> referenced symbols)
    """

    def __init__(self, root="."):
        self.root = Path(root)
        self.file_symbols = {}
        self.symbol_to_file = {}
        self.symbol_to_span = {}
        self.symbol_spans = {}
        self.known_files = set()
        self.file_imports = {}
        self.file_imported_by = {}
        self.symbol_references = {}
        self.file_summaries = {}

    def build(self):
        self.file_symbols = {}
        self.symbol_to_file = {}
        self.symbol_to_span = {}
        self.symbol_spans = {}
        self.known_files = set()
        self.file_imports = {}
        self.file_imported_by = {}
        self.symbol_references = {}
        self.file_summaries = {}
        file_texts = {}
        file_symbol_records = {}

        # First pass: discover files + symbol owners
        for path in self._iter_project_python_files():
            if path.name in DEFAULT_SKIP_FILES:
                continue

            file_name = self._relative_file_name(path)
            self.known_files.add(file_name)

            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            file_texts[file_name] = text

            symbol_records = self._extract_symbol_records(file_name, text)
            file_symbol_records[file_name] = symbol_records
            symbols = [record["symbol"] for record in symbol_records]
            self.file_symbols[file_name] = symbols

            for record in symbol_records:
                symbol = record["symbol"]
                symbol_id = record["symbol_id"]
                self.symbol_to_file.setdefault(symbol, file_name)
                self.symbol_spans[symbol_id] = record
                self.symbol_to_span.setdefault(symbol, record)

        # Build module -> file mapping to resolve imports. Preserve full
        # package identity, while keeping a basename alias only when unambiguous.
        module_to_file = {}
        basename_candidates = {}
        for filename in self.known_files:
            module_name = Path(filename).with_suffix("").as_posix().replace("/", ".")
            module_to_file[module_name] = filename
            basename_candidates.setdefault(Path(filename).stem, []).append(filename)
        for stem, candidates in basename_candidates.items():
            if len(candidates) == 1:
                module_to_file.setdefault(stem, candidates[0])

        # Second pass: build import graph and symbol reference graph
        for path in self._iter_project_python_files():
            if path.name in DEFAULT_SKIP_FILES:
                continue

            file_name = self._relative_file_name(path)
            text = file_texts.get(file_name)
            if text is None:
                continue

            imported_modules = self._extract_import_names(text)
            imported_files = set()

            for module_name in imported_modules:
                target_file = module_to_file.get(module_name)
                if target_file and target_file != file_name:
                    imported_files.add(target_file)

            self.file_imports[file_name] = sorted(imported_files)

            for imported_file in imported_files:
                self.file_imported_by.setdefault(imported_file, []).append(file_name)

            symbol_refs = self._extract_symbol_references(text)
            for owner_symbol, refs in symbol_refs.items():
                self.symbol_references.setdefault(owner_symbol, set()).update(refs)

        for file_name in self.known_files:
            self.file_imported_by.setdefault(file_name, [])

        # Normalize symbol_references sets to lists
        self.symbol_references = {
            sym: sorted(list(refs)) for sym, refs in self.symbol_references.items()
        }

        for file_name, text in file_texts.items():
            symbol_records = file_symbol_records.get(file_name) or []
            imports = self.file_imports.get(file_name, [])
            route_inventory = self._extract_route_branch_inventory(text)
            self.file_summaries[file_name] = self._build_file_summary(
                file_name,
                text,
                symbol_records=symbol_records,
                imports=imports,
                route_branch_inventory=route_inventory,
            )

        return self.to_dict()

    def _relative_file_name(self, path):
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def _iter_project_python_files(self):
        for path in sorted(self.root.rglob("*.py")):
            try:
                relative_parts = path.relative_to(self.root).parts
            except ValueError:
                relative_parts = path.parts

            if any(part in DEFAULT_SKIP_DIRS for part in relative_parts[:-1]):
                continue

            yield path

    def _select_high_value_symbols(self, symbol_records, max_symbols=8):
        scored = []
        for record in symbol_records:
            start = record.get("lineno") or 0
            end = record.get("end_lineno") or start
            span = max(1, end - start)
            name = str(record.get("symbol") or "")
            score = span
            if name in {"main", "route", "plan_task", "generate_patch_with_revisions", "apply_patch"}:
                score += 1000
            scored.append((score, start, record))

        scored.sort(key=lambda item: (-item[0], item[1], str(item[2].get("symbol") or "")))
        return [self._compact_symbol_record(item[2]) for item in scored[:max_symbols]]

    def _compact_symbol_record(self, record):
        return {
            "symbol": record.get("symbol"),
            "symbol_id": record.get("symbol_id"),
            "type": record.get("type"),
            "lineno": record.get("lineno"),
            "end_lineno": record.get("end_lineno"),
        }

    def _extract_route_branch_inventory(self, file_text, max_routes=12):
        routes = []
        seen = set()

        try:
            tree = ast.parse(file_text)
        except SyntaxError:
            return routes

        route_root = tree
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                route_root = node
                break

        for node in ast.walk(route_root):
            if not isinstance(node, ast.Compare):
                continue
            if not isinstance(node.left, ast.Name) or node.left.id != "route":
                continue
            if not node.comparators:
                continue
            comparator = node.comparators[0]
            if not isinstance(comparator, ast.Constant) or not isinstance(comparator.value, str):
                continue
            value = comparator.value
            if value in seen:
                continue
            seen.add(value)
            routes.append(value)
            if len(routes) >= max_routes:
                break

        return routes

    def _build_file_summary(self, file_name, file_text, *, symbol_records, imports, route_branch_inventory):
        symbol_inventory = [self._compact_symbol_record(record) for record in symbol_records]
        return {
            "file": file_name,
            "char_count": len(file_text),
            "line_count": len(file_text.splitlines()),
            "symbol_count": len(symbol_inventory),
            "symbol_inventory": symbol_inventory[:20],
            "import_summary": list(imports)[:12],
            "high_value_symbols": self._select_high_value_symbols(symbol_records),
            "route_branch_inventory": list(route_branch_inventory)[:12],
        }

    def _extract_symbol_records(self, file_name, file_text):
        try:
            tree = ast.parse(file_text)
        except SyntaxError:
            return []

        symbol_records = []

        def add_record(node, symbol_type, parent_name=None):
            symbol_name = node.name
            if parent_name:
                symbol_id = f"{file_name}::{parent_name}.{symbol_name}"
            else:
                symbol_id = f"{file_name}::{symbol_name}"

            symbol_records.append({
                "symbol_id": symbol_id,
                "file": file_name,
                "symbol": symbol_name,
                "lineno": getattr(node, "lineno", None),
                "end_lineno": getattr(node, "end_lineno", None),
                "col_offset": getattr(node, "col_offset", None),
                "end_col_offset": getattr(node, "end_col_offset", None),
                "type": symbol_type,
            })

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add_record(node, "function")

            elif isinstance(node, ast.ClassDef):
                add_record(node, "class")
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        add_record(child, "method", parent_name=node.name)

        return symbol_records

    def _extract_import_names(self, file_text):
        try:
            tree = ast.parse(file_text)
        except SyntaxError:
            return []

        imports = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
                    imports.add(alias.name.split(".")[0])

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
                    imports.add(node.module.split(".")[0])
                    for alias in node.names:
                        if alias.name != "*":
                            imports.add(f"{node.module}.{alias.name}")

        return sorted(list(imports))

    def _extract_symbol_references(self, file_text):
        try:
            tree = ast.parse(file_text)
        except SyntaxError:
            return {}

        symbol_refs = {}

        def collect_refs(node):
            refs = set()

            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Name):
                        refs.add(func.id)
                    elif isinstance(func, ast.Attribute):
                        if isinstance(func.attr, str):
                            refs.add(func.attr)

            return refs

        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                symbol_refs[node.name] = collect_refs(node)

            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, ast.FunctionDef):
                        symbol_refs[child.name] = collect_refs(child)

        return symbol_refs

    def resolve_file(self, symbol_or_file):
        if not symbol_or_file:
            return None

        if symbol_or_file in self.known_files:
            return symbol_or_file

        basename_matches = [
            file_name for file_name in self.known_files
            if Path(file_name).name == symbol_or_file
        ]
        if len(basename_matches) == 1:
            return basename_matches[0]

        return self.symbol_to_file.get(symbol_or_file)

    def get_file_imports(self, file_name):
        return list(self.file_imports.get(file_name, []))

    def get_file_imported_by(self, file_name):
        return list(self.file_imported_by.get(file_name, []))

    def get_local_symbol_references(self, symbol):
        return list(self.symbol_references.get(symbol, []))

    def get_related_files_for_symbol(self, symbol, depth=1):
        owner_file = self.resolve_file(symbol)
        if not owner_file:
            return []

        related = {owner_file}
        frontier = {owner_file}

        for _ in range(depth):
            next_frontier = set()
            for current in frontier:
                next_frontier.update(self.get_file_imports(current))
                next_frontier.update(self.get_file_imported_by(current))

                for sym, refs in self.symbol_references.items():
                    if sym == symbol or self.resolve_file(sym) == current:
                        for ref_symbol in refs:
                            ref_file = self.resolve_file(ref_symbol)
                            if ref_file:
                                next_frontier.add(ref_file)

            next_frontier -= related
            if not next_frontier:
                break

            related.update(next_frontier)
            frontier = next_frontier

        return sorted(related)

    def get_symbols_for_file(self, file_name):
        return list(self.file_symbols.get(file_name, []))

    def get_file_summary(self, file_name):
        summary = self.file_summaries.get(file_name)
        return dict(summary) if summary else None

    def to_dict(self):
        return {
            "known_files": sorted(self.known_files),
            "file_symbols": {k: list(v) for k, v in self.file_symbols.items()},
            "symbol_to_file": dict(self.symbol_to_file),
            "symbol_to_span": dict(self.symbol_to_span),
            "symbol_spans": dict(self.symbol_spans),
            "file_imports": {k: list(v) for k, v in self.file_imports.items()},
            "file_imported_by": {k: list(v) for k, v in self.file_imported_by.items()},
            "symbol_references": {k: list(v) for k, v in self.symbol_references.items()},
            "file_summaries": dict(self.file_summaries),
        }

    @classmethod
    def from_dict(cls, data, root="."):
        inst = cls(root=root)
        data = data or {}

        inst.known_files = set(data.get("known_files", []))
        inst.file_symbols = {
            k: list(v) for k, v in (data.get("file_symbols") or {}).items()
        }
        inst.symbol_to_file = dict(data.get("symbol_to_file") or {})
        inst.symbol_to_span = dict(data.get("symbol_to_span") or {})
        inst.symbol_spans = dict(data.get("symbol_spans") or {})
        inst.file_imports = {
            k: list(v) for k, v in (data.get("file_imports") or {}).items()
        }
        inst.file_imported_by = {
            k: list(v) for k, v in (data.get("file_imported_by") or {}).items()
        }
        inst.symbol_references = {
            k: list(v) for k, v in (data.get("symbol_references") or {}).items()
        }
        inst.file_summaries = {
            k: dict(v) for k, v in (data.get("file_summaries") or {}).items()
        }
        return inst

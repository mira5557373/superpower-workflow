from __future__ import annotations

from pathlib import Path

from superpower_workflow.docs.diagrams import (
    generate_mermaid,
    parse_imports,
    path_to_module,
)


class TestPathToModule:
    def test_regular_file(self, tmp_path: Path):
        base = tmp_path / "src"
        base.mkdir()
        f = base / "mypackage" / "foo.py"
        f.parent.mkdir(parents=True)
        f.touch()
        assert path_to_module(f, base) == "mypackage.foo"

    def test_init_file(self, tmp_path: Path):
        base = tmp_path / "src"
        base.mkdir()
        f = base / "mypackage" / "__init__.py"
        f.parent.mkdir(parents=True)
        f.touch()
        assert path_to_module(f, base) == "mypackage"

    def test_nested_module(self, tmp_path: Path):
        base = tmp_path / "src"
        base.mkdir()
        f = base / "pkg" / "sub" / "deep.py"
        f.parent.mkdir(parents=True)
        f.touch()
        assert path_to_module(f, base) == "pkg.sub.deep"


class TestParseImports:
    def test_import_statement(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("import os\nimport json\n")
        imports = parse_imports(f)
        assert "os" in imports
        assert "json" in imports

    def test_from_import(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("from mypackage.utils import helper\n")
        imports = parse_imports(f)
        assert "mypackage.utils" in imports

    def test_syntax_error_returns_empty(self, tmp_path: Path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n")
        imports = parse_imports(f)
        assert imports == []

    def test_no_imports(self, tmp_path: Path):
        f = tmp_path / "empty.py"
        f.write_text("x = 1\n")
        imports = parse_imports(f)
        assert imports == []


class TestGenerateMermaid:
    def test_generates_graph_header(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "a.py").write_text("from mypkg import b\n")
        (src / "b.py").write_text("")
        result = generate_mermaid(src, project_prefix="mypkg")
        assert result.startswith("graph TD")

    def test_captures_internal_edges(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "a.py").write_text("from mypkg.b import helper\n")
        (src / "b.py").write_text("")
        result = generate_mermaid(src, project_prefix="mypkg")
        assert "mypkg.a" in result
        assert "mypkg.b" in result
        assert "-->" in result

    def test_excludes_external_imports(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "a.py").write_text("import os\nfrom mypkg import b\n")
        (src / "b.py").write_text("")
        result = generate_mermaid(src, project_prefix="mypkg")
        assert "os" not in result

    def test_empty_package(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        result = generate_mermaid(src, project_prefix="mypkg")
        assert result == "graph TD"

    def test_auto_detects_prefix(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "a.py").write_text("from mypkg.b import x\n")
        (src / "b.py").write_text("")
        result = generate_mermaid(src)
        assert "mypkg.a" in result

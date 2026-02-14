"""Tests for import parsing and inheritance detection in language recognizers (v0.6.0).

Covers TypeScript, Rust, and Java recognizers' ability to extract:
    - ImportInfo from source-level import statements
    - ImplementationInfo from class/trait inheritance declarations
"""

import pytest
from pathlib import Path

from codegiraffe.recognizers.typescript import TypeScriptRecognizer
from codegiraffe.recognizers.rust import RustRecognizer
from codegiraffe.recognizers.java import JavaRecognizer
from codegiraffe.scanner import ImportInfo, ImplementationInfo


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------


class TestTypeScriptRecognizerImports:
    """Import parsing and inheritance detection for TypeScript/JavaScript."""

    @pytest.fixture
    def recognizer(self):
        return TypeScriptRecognizer()

    # -- imports --

    def test_es6_named_import(self, recognizer, tmp_path):
        """Named import from a relative path produces ImportInfo with module_path containing 'bar'."""
        src = tmp_path / "foo.ts"
        src.write_text("import { Foo } from './bar';\n")
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 1
        imp = result.imports[0]
        assert isinstance(imp, ImportInfo)
        assert "bar" in imp.module_path
        assert "Foo" in imp.symbols

    def test_es6_named_import_multiple_symbols(self, recognizer, tmp_path):
        """Named import with multiple symbols captures all of them."""
        src = tmp_path / "foo.ts"
        src.write_text("import { Foo, Bar, Baz } from './utils';\n")
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 1
        imp = result.imports[0]
        assert set(imp.symbols) == {"Foo", "Bar", "Baz"}
        assert "utils" in imp.module_path

    def test_default_import(self, recognizer, tmp_path):
        """Default import from a relative path produces ImportInfo."""
        src = tmp_path / "app.ts"
        src.write_text("import Foo from './bar';\n")
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) >= 1
        matching = [i for i in result.imports if "bar" in i.module_path]
        assert len(matching) >= 1
        imp = matching[0]
        assert isinstance(imp, ImportInfo)
        assert "Foo" in imp.symbols

    def test_wildcard_import(self, recognizer, tmp_path):
        """Wildcard (namespace) import produces ImportInfo with style='wildcard'."""
        src = tmp_path / "index.ts"
        src.write_text("import * as Helpers from './helpers';\n")
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) >= 1
        wildcard_imports = [i for i in result.imports if i.style == "wildcard"]
        assert len(wildcard_imports) >= 1
        assert "helpers" in wildcard_imports[0].module_path

    def test_non_relative_import_excluded(self, recognizer, tmp_path):
        """Non-relative imports (e.g. from 'react') are NOT returned."""
        src = tmp_path / "app.tsx"
        src.write_text(
            "import React from 'react';\n"
            "import { useState } from 'react';\n"
            "import * as ReactDOM from 'react-dom';\n"
        )
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 0

    # -- inheritance --

    def test_class_extends(self, recognizer, tmp_path):
        """class extends produces ImplementationInfo."""
        src = tmp_path / "child.ts"
        src.write_text(
            "export class ChildService extends BaseService {\n"
            "    doWork() {}\n"
            "}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        assert len(result.implementations) >= 1
        impl = result.implementations[0]
        assert isinstance(impl, ImplementationInfo)
        assert impl.child_class == "ChildService"
        assert impl.parent_class == "BaseService"

    def test_class_implements(self, recognizer, tmp_path):
        """class implements produces ImplementationInfo."""
        src = tmp_path / "handler.ts"
        src.write_text(
            "export class RequestHandler implements Handler {\n"
            "    handle() {}\n"
            "}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        impls = [i for i in result.implementations if i.parent_class == "Handler"]
        assert len(impls) >= 1
        assert impls[0].child_class == "RequestHandler"

    def test_class_implements_multiple(self, recognizer, tmp_path):
        """class implementing multiple interfaces produces multiple ImplementationInfo."""
        src = tmp_path / "multi.ts"
        src.write_text(
            "export class MultiHandler implements Readable, Writable {\n"
            "    read() {}\n"
            "    write() {}\n"
            "}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        parents = {i.parent_class for i in result.implementations}
        assert "Readable" in parents
        assert "Writable" in parents


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


class TestRustRecognizerImports:
    """Import parsing and trait implementation detection for Rust."""

    @pytest.fixture
    def recognizer(self):
        return RustRecognizer()

    # -- imports --

    def test_use_crate_import(self, recognizer, tmp_path):
        """use crate::module::Symbol produces ImportInfo with style='absolute'."""
        src = tmp_path / "handler.rs"
        src.write_text("use crate::models::User;\n")
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 1
        imp = result.imports[0]
        assert isinstance(imp, ImportInfo)
        assert imp.style == "absolute"
        assert "models" in imp.module_path

    def test_use_super_import(self, recognizer, tmp_path):
        """use super::Symbol produces ImportInfo with style='relative'."""
        src = tmp_path / "sub.rs"
        src.write_text("use super::Config;\n")
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 1
        imp = result.imports[0]
        assert isinstance(imp, ImportInfo)
        assert imp.style == "relative"

    def test_use_crate_nested_path(self, recognizer, tmp_path):
        """Nested crate path is converted to dotted module_path."""
        src = tmp_path / "api.rs"
        src.write_text("use crate::db::schema::users;\n")
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 1
        imp = result.imports[0]
        assert imp.module_path == "db.schema.users"
        assert imp.style == "absolute"

    def test_external_crate_excluded(self, recognizer, tmp_path):
        """External crate imports (e.g. std::) are NOT returned."""
        src = tmp_path / "main.rs"
        src.write_text(
            "use std::collections::HashMap;\n"
            "use serde::Serialize;\n"
            "use tokio::sync::Mutex;\n"
        )
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 0

    # -- trait implementation --

    def test_impl_trait_for_struct(self, recognizer, tmp_path):
        """impl Trait for Struct produces ImplementationInfo."""
        src = tmp_path / "models.rs"
        src.write_text(
            "pub struct UserRepo;\n"
            "\n"
            "impl Repository for UserRepo {\n"
            "    fn find(&self) {}\n"
            "}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        assert len(result.implementations) == 1
        impl = result.implementations[0]
        assert isinstance(impl, ImplementationInfo)
        assert impl.child_class == "UserRepo"
        assert impl.parent_class == "Repository"

    def test_impl_multiple_traits(self, recognizer, tmp_path):
        """Multiple impl blocks for different traits produce multiple ImplementationInfo."""
        src = tmp_path / "entity.rs"
        src.write_text(
            "pub struct Entity;\n"
            "\n"
            "impl Display for Entity {\n"
            "    fn fmt(&self) {}\n"
            "}\n"
            "\n"
            "impl Debug for Entity {\n"
            "    fn fmt(&self) {}\n"
            "}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        assert len(result.implementations) == 2
        parents = {i.parent_class for i in result.implementations}
        assert "Display" in parents
        assert "Debug" in parents
        assert all(i.child_class == "Entity" for i in result.implementations)


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------


class TestJavaRecognizerImports:
    """Import parsing and inheritance detection for Java."""

    @pytest.fixture
    def recognizer(self, tmp_path):
        """Create a JavaRecognizer with project root set for package detection."""
        rec = JavaRecognizer()
        # Create a sibling Java file so the recognizer discovers the project package
        pkg_dir = tmp_path / "com" / "myapp"
        pkg_dir.mkdir(parents=True)
        sibling = pkg_dir / "Application.java"
        sibling.write_text("package com.myapp;\npublic class Application {}\n")
        rec.set_project_root(str(tmp_path))
        return rec

    # -- imports --

    def test_project_import_detected(self, recognizer, tmp_path):
        """Import matching a project package produces ImportInfo."""
        src = tmp_path / "Service.java"
        src.write_text(
            "package com.myapp.service;\n"
            "import com.myapp.model.User;\n"
            "public class UserService {}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 1
        imp = result.imports[0]
        assert isinstance(imp, ImportInfo)
        assert imp.module_path == "com.myapp.model.User"
        assert "User" in imp.symbols
        assert imp.style == "absolute"

    def test_stdlib_import_excluded(self, recognizer, tmp_path):
        """Standard library imports (java.util.*) are NOT returned."""
        src = tmp_path / "Util.java"
        src.write_text(
            "package com.myapp.util;\n"
            "import java.util.List;\n"
            "import java.util.Map;\n"
            "import java.io.File;\n"
            "public class Util {}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 0

    def test_third_party_import_excluded(self, recognizer, tmp_path):
        """Third-party imports not matching project packages are excluded."""
        src = tmp_path / "Controller.java"
        src.write_text(
            "package com.myapp.web;\n"
            "import org.springframework.web.bind.annotation.RestController;\n"
            "import javax.inject.Inject;\n"
            "public class MyController {}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        assert len(result.imports) == 0

    # -- inheritance --

    def test_class_extends(self, recognizer, tmp_path):
        """class X extends Y produces ImplementationInfo."""
        src = tmp_path / "Child.java"
        src.write_text(
            "package com.myapp;\n"
            "public class ChildService extends BaseService {\n"
            "}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        assert len(result.implementations) >= 1
        impl = result.implementations[0]
        assert isinstance(impl, ImplementationInfo)
        assert impl.child_class == "ChildService"
        assert impl.parent_class == "BaseService"

    def test_class_implements_single(self, recognizer, tmp_path):
        """class X implements Y produces ImplementationInfo."""
        src = tmp_path / "Repo.java"
        src.write_text(
            "package com.myapp;\n"
            "public class UserRepo implements Repository {\n"
            "}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        impls = [i for i in result.implementations if i.parent_class == "Repository"]
        assert len(impls) == 1
        assert impls[0].child_class == "UserRepo"

    def test_class_implements_multiple(self, recognizer, tmp_path):
        """class X implements Y, Z produces multiple ImplementationInfo entries."""
        src = tmp_path / "Handler.java"
        src.write_text(
            "package com.myapp;\n"
            "public class EventHandler implements Serializable, Comparable {\n"
            "}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        parents = {i.parent_class for i in result.implementations}
        assert "Serializable" in parents
        assert "Comparable" in parents
        children = {i.child_class for i in result.implementations}
        assert "EventHandler" in children

    def test_class_extends_and_implements(self, recognizer, tmp_path):
        """class X extends Y implements Z produces both ImplementationInfo entries."""
        src = tmp_path / "Worker.java"
        src.write_text(
            "package com.myapp;\n"
            "public class TaskWorker extends AbstractWorker implements Runnable {\n"
            "}\n"
        )
        result = recognizer.recognize(src, src.read_text())

        parents = {i.parent_class for i in result.implementations}
        assert "AbstractWorker" in parents
        assert "Runnable" in parents
        assert all(i.child_class == "TaskWorker" for i in result.implementations)

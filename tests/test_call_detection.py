"""Tests for call-graph detection across language recognizers (v0.9.0)."""

import pytest
from pathlib import Path

from codegiraffe.scanner import CallInfo, InterfaceInfo, MethodSetEntry, PythonRecognizer, ScanResult
from codegiraffe.recognizers.go import GoRecognizer
from codegiraffe.recognizers.typescript import TypeScriptRecognizer


class TestGoCallDetection:
    """Test Go call-graph extraction."""

    def _recognize(self, code: str, filename: str = "internal/app/app.go") -> ScanResult:
        rec = GoRecognizer()
        rec.set_project_root("/fake/project")
        return rec.recognize(Path(filename), code)

    def test_method_call_on_field(self):
        code = '''package app
func (a *App) Update() {
    a.Store.Save(data)
}
'''
        result = self._recognize(code)
        store_calls = [c for c in result.calls if c.receiver == "Store" and c.callee == "Save"]
        assert len(store_calls) >= 1
        assert store_calls[0].style == "method"

    def test_package_function_call(self):
        code = '''package app
func main() {
    store.NewSQLiteStore()
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "NewSQLiteStore"]
        assert len(calls) >= 1
        assert calls[0].receiver == "store"

    def test_plain_function_call(self):
        code = '''package app
func main() {
    HandleKeyEvent(msg)
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "HandleKeyEvent"]
        assert len(calls) >= 1
        assert calls[0].style == "direct"

    def test_stdlib_excluded(self):
        code = '''package app
func main() {
    fmt.Println("hello")
    log.Fatal("error")
    os.Exit(1)
}
'''
        result = self._recognize(code)
        stdlib_calls = [c for c in result.calls if c.receiver in ("fmt", "log", "os")]
        assert len(stdlib_calls) == 0

    def test_caller_from_method_receiver(self):
        code = '''package app
func (a *App) Update() {
    a.Store.Save(data)
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "Save"]
        assert len(calls) >= 1
        assert calls[0].caller == "App.Update"

    def test_interface_detection(self):
        code = '''package store
type Store interface {
    Get(key string) ([]byte, error)
    Put(key string, value []byte) error
}
'''
        result = self._recognize(code)
        ifaces = [i for i in result.interfaces if i.name == "Store"]
        assert len(ifaces) == 1
        assert len(ifaces[0].methods) == 2
        assert "Get" in ifaces[0].methods
        assert "Put" in ifaces[0].methods

    def test_method_set_detection(self):
        code = '''package store
func (s *SQLiteStore) Get(key string) ([]byte, error) {
    return nil, nil
}
func (s *SQLiteStore) Put(key string, value []byte) error {
    return nil
}
'''
        result = self._recognize(code)
        entries = [m for m in result.method_sets if m.struct_name == "SQLiteStore"]
        assert len(entries) == 2
        methods = {m.method_name for m in entries}
        assert methods == {"Get", "Put"}

    def test_multiple_calls_in_function(self):
        code = '''package app
func (a *App) Init() {
    a.Config.Load()
    a.Store.Open()
    a.Server.Start()
}
'''
        result = self._recognize(code)
        assert len(result.calls) >= 3


class TestPythonCallDetection:
    """Test Python call-graph extraction."""

    def _recognize(self, code: str, filename: str = "services/app.py") -> ScanResult:
        rec = PythonRecognizer()
        return rec.recognize(Path(filename), code)

    def test_self_method_call(self):
        code = '''class App:
    def update(self):
        self.process()
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "process"]
        assert len(calls) >= 1
        assert calls[0].style == "method"

    def test_self_method_receiver_is_class(self):
        code = '''class App:
    def update(self):
        self.process()
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "process"]
        assert len(calls) >= 1
        assert calls[0].receiver == "App"

    def test_constructor_call(self):
        code = '''def main():
    service = MyService()
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "MyService"]
        assert len(calls) >= 1
        assert calls[0].style == "constructor"

    def test_object_method_call(self):
        code = '''def handler():
    db.query("SELECT 1")
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "query" and c.receiver == "db"]
        assert len(calls) >= 1
        assert calls[0].style == "method"

    def test_direct_function_call(self):
        code = '''def main():
    process_data()
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "process_data"]
        assert len(calls) >= 1
        assert calls[0].style == "direct"

    def test_builtins_excluded(self):
        code = '''def main():
    print("hello")
    x = len([1,2,3])
    r = range(10)
'''
        result = self._recognize(code)
        builtin_calls = [c for c in result.calls if c.callee in ("print", "len", "range")]
        assert len(builtin_calls) == 0

    def test_caller_context(self):
        code = '''def handle_request():
    db.query("SELECT 1")
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "query"]
        assert len(calls) >= 1
        assert calls[0].caller == "handle_request"

    def test_caller_context_in_class(self):
        code = '''class UserService:
    def get_user(self):
        db.query("SELECT 1")
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "query"]
        assert len(calls) >= 1
        assert calls[0].caller == "UserService.get_user"

    def test_file_path_set(self):
        code = '''def main():
    process()
'''
        result = self._recognize(code, "src/main.py")
        calls = [c for c in result.calls if c.callee == "process"]
        assert len(calls) >= 1
        assert calls[0].file_path == "src/main.py"

    def test_import_lines_excluded(self):
        code = '''from os import path
import json
def main():
    process()
'''
        result = self._recognize(code)
        import_calls = [c for c in result.calls if c.callee in ("path", "json")]
        assert len(import_calls) == 0

    def test_decorator_lines_excluded(self):
        code = '''@app.route("/test")
def handler():
    pass
'''
        result = self._recognize(code)
        # "route" from decorator should not appear as a call
        decorator_calls = [c for c in result.calls if c.callee == "route"]
        assert len(decorator_calls) == 0

    def test_multiple_calls_in_method(self):
        code = '''class Service:
    def process(self):
        self.validate()
        self.transform()
        db.save()
'''
        result = self._recognize(code)
        assert len(result.calls) >= 3


class TestTypeScriptCallDetection:
    """Test TypeScript call-graph extraction."""

    def _recognize(self, code: str, filename: str = "src/app.ts") -> ScanResult:
        rec = TypeScriptRecognizer()
        return rec.recognize(Path(filename), code)

    def test_this_method_call(self):
        code = '''class App {
    render() {
        this.update();
    }
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "update"]
        assert len(calls) >= 1
        assert calls[0].style == "method"

    def test_this_method_receiver_is_class(self):
        code = '''class App {
    render() {
        this.update();
    }
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "update"]
        assert len(calls) >= 1
        assert calls[0].receiver == "App"

    def test_object_method_call(self):
        code = '''function handler() {
    service.fetchData();
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "fetchData" and c.receiver == "service"]
        assert len(calls) >= 1
        assert calls[0].style == "method"

    def test_constructor_call(self):
        code = '''function main() {
    const svc = new UserService();
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "UserService"]
        assert len(calls) >= 1
        assert calls[0].style == "constructor"

    def test_builtins_excluded(self):
        code = '''function main() {
    console.log("hello");
    JSON.parse("{}");
}
'''
        result = self._recognize(code)
        builtin_calls = [c for c in result.calls if c.receiver in ("console", "JSON")]
        assert len(builtin_calls) == 0

    def test_direct_function_call(self):
        code = '''function main() {
    processData();
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "processData"]
        assert len(calls) >= 1
        assert calls[0].style == "direct"

    def test_caller_context(self):
        code = '''function handleRequest() {
    db.query("SELECT 1");
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "query"]
        assert len(calls) >= 1
        assert calls[0].caller == "handleRequest"

    def test_caller_context_in_class(self):
        code = '''class UserController {
    getUser() {
        this.service.find();
    }
}
'''
        result = self._recognize(code)
        calls = [c for c in result.calls if c.callee == "find"]
        assert len(calls) >= 1
        assert calls[0].caller == "UserController.getUser"

    def test_file_path_set(self):
        code = '''function main() {
    processData();
}
'''
        result = self._recognize(code, "src/handler.ts")
        calls = [c for c in result.calls if c.callee == "processData"]
        assert len(calls) >= 1
        assert calls[0].file_path == "src/handler.ts"

    def test_import_lines_excluded(self):
        code = '''import { something } from "./module";
function main() {
    doWork();
}
'''
        result = self._recognize(code)
        import_calls = [c for c in result.calls if c.callee == "something"]
        assert len(import_calls) == 0

    def test_multiple_calls_in_method(self):
        code = '''class Service {
    process() {
        this.validate();
        this.transform();
        db.save();
    }
}
'''
        result = self._recognize(code)
        assert len(result.calls) >= 3

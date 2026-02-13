"""Tests for AST-aware scanning using tree-sitter.

Tests are split into two groups:
1. Tests that require tree-sitter and its language packages (skipped if not installed)
2. Tests that verify graceful behavior without tree-sitter installed
"""

import pytest
from pathlib import Path

# Check if tree-sitter and all language packages are available.
# This mirrors the detection logic in codegiraffe.ast_scanner.
try:
    import tree_sitter  # noqa: F401
    import tree_sitter_python  # noqa: F401
    import tree_sitter_go  # noqa: F401
    import tree_sitter_typescript  # noqa: F401
    import tree_sitter_rust  # noqa: F401
    import tree_sitter_java  # noqa: F401
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

from codegiraffe.scanner import ScanResult, PatternRecognizer
from codegiraffe.schema import NodeType, EdgeType


# ---------------------------------------------------------------------------
# Tests that do NOT require tree-sitter (always run)
# ---------------------------------------------------------------------------


class TestAvailabilityWithout:
    """Tests that verify ast_scanner works without tree-sitter installed."""

    def test_import_does_not_crash(self):
        """Importing ast_scanner should never raise, even without tree-sitter."""
        import codegiraffe.ast_scanner  # noqa: F401

    def test_is_available_returns_bool(self):
        """is_available() should return a boolean matching actual availability."""
        from codegiraffe.ast_scanner import is_available
        result = is_available()
        assert isinstance(result, bool)
        assert result == HAS_TREE_SITTER


# ---------------------------------------------------------------------------
# Tests that REQUIRE tree-sitter-languages
# ---------------------------------------------------------------------------

requires_tree_sitter = pytest.mark.skipif(
    not HAS_TREE_SITTER,
    reason="tree-sitter-languages not installed",
)


@requires_tree_sitter
class TestPythonASTRecognizer:
    """Test PythonASTRecognizer detection capabilities."""

    @pytest.fixture
    def recognizer(self):
        from codegiraffe.ast_scanner import PythonASTRecognizer
        return PythonASTRecognizer()

    def test_implements_protocol(self, recognizer):
        """PythonASTRecognizer must satisfy PatternRecognizer protocol."""
        assert isinstance(recognizer, PatternRecognizer)

    def test_flask_routes(self, recognizer):
        content = '''
from flask import Flask
app = Flask(__name__)

@app.route("/api/users")
def get_users():
    return []

@app.route("/api/items", methods=["POST"])
def create_item():
    return {}
'''
        result = recognizer.recognize(Path("app.py"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids
        assert "endpoint:/api/items" in ids
        assert all(
            n.type == NodeType.ENDPOINT
            for n in result.nodes
            if n.id.startswith("endpoint:")
        )

    def test_fastapi_routes(self, recognizer):
        content = '''
from fastapi import FastAPI
app = FastAPI()

@app.get("/users/{user_id}")
async def read_user(user_id: int):
    return {"user_id": user_id}

@app.post("/users")
async def create_user():
    return {}
'''
        result = recognizer.recognize(Path("main.py"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/users/{user_id}" in ids
        assert "endpoint:/users" in ids

    def test_sqlalchemy_models(self, recognizer):
        content = '''
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
'''
        result = recognizer.recognize(Path("models.py"), content)
        ids = {n.id for n in result.nodes}
        assert "table:users" in ids
        table_nodes = [n for n in result.nodes if n.type == NodeType.DATABASE_TABLE]
        assert len(table_nodes) >= 1
        assert table_nodes[0].metadata.get("class_name") == "User"

    def test_celery_tasks(self, recognizer):
        content = '''
from celery import Celery
app = Celery("tasks")

@app.task
def send_email(to, subject, body):
    pass

@app.task()
def process_payment(order_id):
    pass
'''
        result = recognizer.recognize(Path("tasks.py"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:send_email" in ids
        assert "worker:process_payment" in ids
        worker_nodes = [n for n in result.nodes if n.type == NodeType.WORKER]
        assert len(worker_nodes) >= 2

    def test_env_vars_getenv(self, recognizer):
        content = '''
import os
db_url = os.getenv("DATABASE_URL")
secret = os.getenv("SECRET_KEY", "default")
'''
        result = recognizer.recognize(Path("config.py"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DATABASE_URL" in ids
        assert "env:SECRET_KEY" in ids
        env_nodes = [n for n in result.nodes if n.type == NodeType.ENV_VAR]
        assert len(env_nodes) >= 2

    def test_env_vars_environ(self, recognizer):
        content = '''
import os
db_url = os.environ["DATABASE_URL"]
port = os.environ.get("PORT", "8080")
'''
        result = recognizer.recognize(Path("config.py"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DATABASE_URL" in ids
        assert "env:PORT" in ids

    def test_external_api_calls(self, recognizer):
        content = '''
import requests
response = requests.get("https://api.example.com/data")
result = requests.post("https://api.example.com/submit")
'''
        result = recognizer.recognize(Path("client.py"), content)
        ids = {n.id for n in result.nodes}
        assert "api:https://api.example.com/data" in ids
        assert "api:https://api.example.com/submit" in ids
        api_nodes = [n for n in result.nodes if n.type == NodeType.EXTERNAL_API]
        assert len(api_nodes) >= 2

    def test_class_definitions_as_service_fallback(self, recognizer):
        content = '''
class UserService:
    def get_user(self, user_id):
        pass

class OrderProcessor:
    def process(self, order):
        pass
'''
        result = recognizer.recognize(Path("services.py"), content)
        ids = {n.id for n in result.nodes}
        assert "service:UserService" in ids
        assert "service:OrderProcessor" in ids
        svc_nodes = [n for n in result.nodes if n.type == NodeType.SERVICE]
        assert len(svc_nodes) >= 2

    def test_empty_file(self, recognizer):
        result = recognizer.recognize(Path("empty.py"), "")
        assert isinstance(result, ScanResult)
        assert result.nodes == []
        assert result.edges == []

    def test_syntax_errors_handled_gracefully(self, recognizer):
        """tree-sitter should handle partial/broken syntax gracefully."""
        content = '''
def broken_function(
    # Missing closing paren and colon
class AlsoValid:
    pass
'''
        result = recognizer.recognize(Path("broken.py"), content)
        # Should not raise; may detect some nodes from valid parts
        assert isinstance(result, ScanResult)

    def test_returns_scan_result(self, recognizer):
        result = recognizer.recognize(Path("test.py"), "x = 1")
        assert isinstance(result, ScanResult)

    def test_endpoint_edge_inference(self, recognizer):
        """When endpoints and DB tables coexist, edges should be inferred."""
        content = '''
from flask import Flask
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()
app = Flask(__name__)

class Order(Base):
    __tablename__ = "orders"
    id = 1

@app.route("/api/orders")
def get_orders():
    return Order.query.all()
'''
        result = recognizer.recognize(Path("views.py"), content)
        endpoint_ids = {n.id for n in result.nodes if n.type == NodeType.ENDPOINT}
        table_ids = {n.id for n in result.nodes if n.type == NodeType.DATABASE_TABLE}
        assert len(endpoint_ids) >= 1
        assert len(table_ids) >= 1
        # Should have at least one edge inferred
        if endpoint_ids and table_ids:
            assert len(result.edges) >= 1


@requires_tree_sitter
class TestGoASTRecognizer:
    """Test GoASTRecognizer detection capabilities."""

    @pytest.fixture
    def recognizer(self):
        from codegiraffe.ast_scanner import GoASTRecognizer
        return GoASTRecognizer()

    def test_implements_protocol(self, recognizer):
        assert isinstance(recognizer, PatternRecognizer)

    def test_struct_definitions(self, recognizer):
        content = '''
package main

type UserService struct {
    db *sql.DB
}

type OrderHandler struct {
    service OrderService
}
'''
        result = recognizer.recognize(Path("main.go"), content)
        ids = {n.id for n in result.nodes}
        assert "service:UserService" in ids
        assert "service:OrderHandler" in ids

    def test_os_getenv(self, recognizer):
        content = '''
package main

import "os"

func main() {
    dbHost := os.Getenv("DB_HOST")
    port := os.Getenv("PORT")
}
'''
        result = recognizer.recognize(Path("config.go"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DB_HOST" in ids
        assert "env:PORT" in ids

    def test_empty_file(self, recognizer):
        result = recognizer.recognize(Path("empty.go"), "")
        assert isinstance(result, ScanResult)
        assert result.nodes == []


@requires_tree_sitter
class TestTypeScriptASTRecognizer:
    """Test TypeScriptASTRecognizer detection capabilities."""

    @pytest.fixture
    def recognizer(self):
        from codegiraffe.ast_scanner import TypeScriptASTRecognizer
        return TypeScriptASTRecognizer()

    def test_implements_protocol(self, recognizer):
        assert isinstance(recognizer, PatternRecognizer)

    def test_express_routes(self, recognizer):
        content = '''
import express from 'express';
const app = express();
app.get("/api/users", (req, res) => { res.json([]); });
app.post("/api/items", (req, res) => { res.status(201).json({}); });
'''
        result = recognizer.recognize(Path("app.ts"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids
        assert "endpoint:/api/items" in ids

    def test_process_env(self, recognizer):
        content = '''
const dbUrl = process.env.DATABASE_URL;
const port = process.env["PORT"];
'''
        result = recognizer.recognize(Path("config.ts"), content)
        ids = {n.id for n in result.nodes}
        # Should detect at least one env var
        env_nodes = [n for n in result.nodes if n.type == NodeType.ENV_VAR]
        assert len(env_nodes) >= 1


@requires_tree_sitter
class TestRustASTRecognizer:
    """Test RustASTRecognizer detection capabilities."""

    @pytest.fixture
    def recognizer(self):
        from codegiraffe.ast_scanner import RustASTRecognizer
        return RustASTRecognizer()

    def test_implements_protocol(self, recognizer):
        assert isinstance(recognizer, PatternRecognizer)

    def test_actix_routes(self, recognizer):
        content = '''
use actix_web::{get, post, web, HttpResponse};

#[get("/api/health")]
async fn health() -> HttpResponse {
    HttpResponse::Ok().finish()
}

#[post("/api/submit")]
async fn submit() -> HttpResponse {
    HttpResponse::Ok().finish()
}
'''
        result = recognizer.recognize(Path("main.rs"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/health" in ids
        assert "endpoint:/api/submit" in ids

    def test_struct_definitions(self, recognizer):
        content = '''
struct AppState {
    db: Pool<Postgres>,
}

struct Config {
    port: u16,
}
'''
        result = recognizer.recognize(Path("state.rs"), content)
        ids = {n.id for n in result.nodes}
        assert "service:AppState" in ids
        assert "service:Config" in ids


@requires_tree_sitter
class TestJavaASTRecognizer:
    """Test JavaASTRecognizer detection capabilities."""

    @pytest.fixture
    def recognizer(self):
        from codegiraffe.ast_scanner import JavaASTRecognizer
        return JavaASTRecognizer()

    def test_implements_protocol(self, recognizer):
        assert isinstance(recognizer, PatternRecognizer)

    def test_spring_annotations(self, recognizer):
        content = '''
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class UserController {
    @GetMapping("/users")
    public List<User> getUsers() {
        return userService.findAll();
    }

    @PostMapping("/users")
    public User createUser() {
        return userService.create();
    }
}
'''
        result = recognizer.recognize(Path("UserController.java"), content)
        ids = {n.id for n in result.nodes}
        # Should detect endpoint nodes from Spring annotations
        endpoint_nodes = [n for n in result.nodes if n.type == NodeType.ENDPOINT]
        assert len(endpoint_nodes) >= 1

    def test_entity_annotation(self, recognizer):
        content = '''
import javax.persistence.*;

@Entity
@Table(name = "users")
public class User {
    @Id
    private Long id;
    private String name;
}
'''
        result = recognizer.recognize(Path("User.java"), content)
        ids = {n.id for n in result.nodes}
        table_nodes = [n for n in result.nodes if n.type == NodeType.DATABASE_TABLE]
        assert len(table_nodes) >= 1


@requires_tree_sitter
class TestGetASTRegistry:
    """Test the get_ast_registry helper function."""

    def test_returns_registry(self):
        from codegiraffe.ast_scanner import get_ast_registry
        from codegiraffe.registry import RecognizerRegistry
        registry = get_ast_registry()
        assert isinstance(registry, RecognizerRegistry)

    def test_correct_extensions_registered(self):
        from codegiraffe.ast_scanner import get_ast_registry
        registry = get_ast_registry()
        exts = registry.registered_extensions
        assert ".py" in exts
        assert ".pyi" in exts
        assert ".go" in exts
        assert ".ts" in exts
        assert ".tsx" in exts
        assert ".rs" in exts
        assert ".java" in exts

    def test_recognizers_for_python_file(self):
        from codegiraffe.ast_scanner import get_ast_registry, PythonASTRecognizer
        registry = get_ast_registry()
        recognizers = registry.get_recognizers(Path("app.py"))
        assert any(isinstance(r, PythonASTRecognizer) for r in recognizers)

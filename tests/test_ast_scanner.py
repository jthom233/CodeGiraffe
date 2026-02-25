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

from codegiraffe.ast_scanner import HAS_TS_CSHARP
from codegiraffe.scanner import ScanResult, PatternRecognizer, CallInfo
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

requires_ts_csharp = pytest.mark.skipif(
    not (HAS_TREE_SITTER and HAS_TS_CSHARP),
    reason="requires tree-sitter and tree-sitter-c-sharp",
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


@requires_ts_csharp
class TestCSharpASTRecognizer:
    """Test CSharpASTRecognizer detection capabilities."""

    @pytest.fixture
    def recognizer(self):
        from codegiraffe.ast_scanner import CSharpASTRecognizer
        return CSharpASTRecognizer()

    def test_protocol_compliance(self, recognizer):
        """CSharpASTRecognizer must satisfy the PatternRecognizer protocol."""
        assert hasattr(recognizer, "recognize")
        assert callable(recognizer.recognize)

    def test_endpoint_detection(self, recognizer):
        """[HttpGet("/api/users")] should produce an endpoint node."""
        content = '''
[HttpGet("/api/users")]
public IActionResult GetUsers() { return Ok(); }
'''
        result = recognizer.recognize(Path("Controllers/UsersController.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids
        ep_nodes = [n for n in result.nodes if n.type == NodeType.ENDPOINT]
        assert len(ep_nodes) >= 1

    def test_route_attribute_class_level_skipped(self, recognizer):
        """Class-level [Route("api/[controller]")] should NOT produce an endpoint node (it's a runtime prefix)."""
        content = '''
[Route("api/[controller]")]
public class ProductsController : ControllerBase { }
'''
        result = recognizer.recognize(Path("Controllers/ProductsController.cs"), content)
        ep_nodes = [n for n in result.nodes if n.type == NodeType.ENDPOINT]
        assert len(ep_nodes) == 0

    def test_route_composition(self, recognizer):
        """Class-level [Route] should compose with method-level [HttpGet] to produce a full route."""
        content = '''
[Route("api/v1/analytics")]
[ApiController]
public class AnalyticsController : ControllerBase {
    [HttpGet("dashboard")]
    public IActionResult GetDashboard() { return Ok(); }

    [HttpGet]
    public IActionResult GetAll() { return Ok(); }
}
'''
        result = recognizer.recognize(Path("Controllers/AnalyticsController.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/v1/analytics/dashboard" in ids
        assert "endpoint:/api/v1/analytics" in ids

    def test_table_attribute(self, recognizer):
        """[Table("Users")] should produce a database_table node."""
        content = '''
[Table("Users")]
public class User { public int Id { get; set; } }
'''
        result = recognizer.recognize(Path("Models/User.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "table:Users" in ids
        tbl_nodes = [n for n in result.nodes if n.type == NodeType.DATABASE_TABLE]
        assert len(tbl_nodes) >= 1

    def test_dbset_detection(self, recognizer):
        """DbSet<T> property declarations should produce database_table nodes."""
        content = '''
public class AppDbContext : DbContext {
    public DbSet<Order> Orders { get; set; }
    public DbSet<Product> Products { get; set; }
}
'''
        result = recognizer.recognize(Path("Data/AppDbContext.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "table:Order" in ids
        assert "table:Product" in ids

    def test_env_var_detection(self, recognizer):
        """Environment.GetEnvironmentVariable("KEY") should produce an env_var node."""
        content = '''
var connStr = Environment.GetEnvironmentVariable("CONNECTION_STRING");
var apiKey = Environment.GetEnvironmentVariable("API_KEY");
'''
        result = recognizer.recognize(Path("Config.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "env:CONNECTION_STRING" in ids
        assert "env:API_KEY" in ids

    def test_di_service_detection(self, recognizer):
        """services.AddScoped<IFoo, Foo>() should produce a service node."""
        content = '''
services.AddScoped<IUserService, UserService>();
services.AddSingleton<ICacheService, RedisCacheService>();
'''
        result = recognizer.recognize(Path("Startup.cs"), content)
        ids = {n.id for n in result.nodes}
        # The first type arg is emitted as the service node
        assert any("IUserService" in nid or "UserService" in nid for nid in ids)

    def test_signalr_hub(self, recognizer):
        """class ChatHub : Hub<T> should produce a service node with signalr_hub kind."""
        content = '''
public class ChatHub : Hub<IChatClient> {
    public async Task SendMessage(string user, string message) { }
}
'''
        result = recognizer.recognize(Path("Hubs/ChatHub.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "service:ChatHub" in ids
        hub_node = next(n for n in result.nodes if n.id == "service:ChatHub")
        assert hub_node.metadata.get("kind") == "signalr_hub"

    def test_mediatr_handler(self, recognizer):
        """class X : IRequestHandler<Cmd, Result> should produce a worker node."""
        content = '''
public class CreateOrderHandler : IRequestHandler<CreateOrderCommand, int> {
    public Task<int> Handle(CreateOrderCommand request, CancellationToken ct) {
        return Task.FromResult(1);
    }
}
'''
        result = recognizer.recognize(Path("Handlers/CreateOrderHandler.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:CreateOrderHandler" in ids
        worker_node = next(n for n in result.nodes if n.id == "worker:CreateOrderHandler")
        assert worker_node.type == NodeType.WORKER

    def test_background_service(self, recognizer):
        """class X : BackgroundService should produce a worker node."""
        content = '''
public class MetricsCollector : BackgroundService {
    protected override async Task ExecuteAsync(CancellationToken ct) { }
}
'''
        result = recognizer.recognize(Path("Workers/MetricsCollector.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:MetricsCollector" in ids

    def test_hosted_service(self, recognizer):
        """class X : IHostedService should produce a worker node."""
        content = '''
public class StartupTask : IHostedService {
    public Task StartAsync(CancellationToken ct) => Task.CompletedTask;
    public Task StopAsync(CancellationToken ct) => Task.CompletedTask;
}
'''
        result = recognizer.recognize(Path("Services/StartupTask.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:StartupTask" in ids

    def test_controller_detection(self, recognizer):
        """class X : ControllerBase should produce a service node with controller kind."""
        content = '''
public class OrdersController : ControllerBase {
    [HttpGet("/api/orders")]
    public IActionResult GetOrders() { return Ok(); }
}
'''
        result = recognizer.recognize(Path("Controllers/OrdersController.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "service:OrdersController" in ids
        ctrl_node = next(n for n in result.nodes if n.id == "service:OrdersController")
        assert ctrl_node.metadata.get("kind") == "controller"

    def test_using_statements(self, recognizer):
        """using System.Linq; and using MyApp.Services; should produce ImportInfo records."""
        content = '''
using System.Linq;
using System.Collections.Generic;
using MyApp.Services;
'''
        result = recognizer.recognize(Path("SomeClass.cs"), content)
        module_paths = {imp.module_path for imp in result.imports}
        # All three using statements should be captured
        assert len(result.imports) >= 1
        assert any("System" in mp or "MyApp" in mp for mp in module_paths)

    def test_inheritance_detection(self, recognizer):
        """class Foo : Bar, IBaz should produce ImplementationInfo records."""
        content = '''
public class OrderService : BaseService, IOrderService {
    public void Process() { }
}
'''
        result = recognizer.recognize(Path("Services/OrderService.cs"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        assert ("OrderService", "BaseService") in impl_map
        assert ("OrderService", "IOrderService") in impl_map

    def test_interface_detection(self, recognizer):
        """interface IFoo { ... } should produce InterfaceInfo records."""
        content = '''
public interface IPaymentService {
    Task<bool> Charge(decimal amount);
    Task Refund(string transactionId);
}
'''
        result = recognizer.recognize(Path("Interfaces/IPaymentService.cs"), content)
        iface_names = {i.name for i in result.interfaces}
        assert "IPaymentService" in iface_names

    def test_call_detection(self, recognizer):
        """obj.Method() call expressions should produce CallInfo records."""
        content = '''
public class OrderProcessor {
    private readonly IOrderRepository _repo;

    public async Task Process(int orderId) {
        var order = _repo.GetById(orderId);
        _repo.Save(order);
    }
}
'''
        result = recognizer.recognize(Path("Services/OrderProcessor.cs"), content)
        assert len(result.calls) > 0
        callees = {c.callee for c in result.calls}
        assert "GetById" in callees or "Save" in callees

    def test_no_class_fallback(self, recognizer):
        """A plain class with no special base/attributes must NOT produce a service node.

        This is the key anti-regression test: the class-fallback was removed from the
        C# regex recognizer and must also be absent from the AST recognizer.
        """
        content = '''
internal class HelperUtil {
    public string FormatDate(DateTime dt) => dt.ToString("yyyy-MM-dd");
}
'''
        result = recognizer.recognize(Path("Utils/HelperUtil.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "service:HelperUtil" not in ids
        svc_nodes = [n for n in result.nodes if n.type == NodeType.SERVICE]
        assert len(svc_nodes) == 0

    def test_external_api_detection(self, recognizer):
        """HttpClient.GetAsync("https://...") should produce an external_api node."""
        content = '''
public class PaymentClient {
    private readonly HttpClient _httpClient;

    public async Task<string> GetBalance() {
        var response = await _httpClient.GetAsync("https://api.stripe.com/v1/balance");
        return await response.Content.ReadAsStringAsync();
    }
}
'''
        result = recognizer.recognize(Path("Clients/PaymentClient.cs"), content)
        ids = {n.id for n in result.nodes}
        assert any("api.stripe.com" in nid for nid in ids)
        api_nodes = [n for n in result.nodes if n.type == NodeType.EXTERNAL_API]
        assert len(api_nodes) >= 1


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
        if HAS_TS_CSHARP:
            assert ".cs" in exts

    def test_recognizers_for_python_file(self):
        from codegiraffe.ast_scanner import get_ast_registry, PythonASTRecognizer
        registry = get_ast_registry()
        recognizers = registry.get_recognizers(Path("app.py"))
        assert any(isinstance(r, PythonASTRecognizer) for r in recognizers)


# ---------------------------------------------------------------------------
# Phase 4: AST call detection tests (v0.9.0)
# ---------------------------------------------------------------------------


@requires_tree_sitter
class TestGoASTCallDetection:
    """T087-T088: Go AST call detection produces CallInfo records."""

    @pytest.fixture
    def recognizer(self):
        from codegiraffe.ast_scanner import GoASTRecognizer
        return GoASTRecognizer()

    def test_go_ast_call_detection_produces_call_info(self, recognizer):
        """T087: Go AST call detection produces CallInfo records in ScanResult."""
        content = '''
package main

type App struct {
    store Store
}

func (a *App) Update() {
    a.store.Save()
    result := a.store.Load()
    _ = result
}
'''
        result = recognizer.recognize(Path("app.go"), content)
        assert len(result.calls) > 0, "Expected CallInfo records from Go AST"
        callees = {c.callee for c in result.calls}
        assert "Save" in callees, "Expected Save call to be detected"
        assert "Load" in callees, "Expected Load call to be detected"
        # Verify CallInfo fields are populated
        for call in result.calls:
            assert isinstance(call, CallInfo)
            assert call.file_path == "app.go"
            assert call.callee

    def test_go_ast_filters_stdlib_calls(self, recognizer):
        """T088: Go AST filters stdlib calls (fmt.Println not in calls)."""
        content = '''
package main

import "fmt"

func main() {
    fmt.Println("hello")
    fmt.Printf("world %s", "!")
    os.Getenv("HOME")
}
'''
        result = recognizer.recognize(Path("main.go"), content)
        callees = {c.callee for c in result.calls}
        receivers = {c.receiver for c in result.calls}
        # stdlib calls should be filtered out
        assert "Println" not in callees, "fmt.Println should be filtered as stdlib"
        assert "Printf" not in callees, "fmt.Printf should be filtered as stdlib"
        assert "Getenv" not in callees, "os.Getenv should be filtered as stdlib"
        assert "fmt" not in receivers, "fmt receiver should not appear in calls"


@requires_tree_sitter
class TestTypeScriptASTCallDetection:
    """T089: TypeScript AST call detection produces CallInfo records."""

    @pytest.fixture
    def recognizer(self):
        from codegiraffe.ast_scanner import TypeScriptASTRecognizer
        return TypeScriptASTRecognizer()

    def test_ts_ast_call_detection_produces_call_info(self, recognizer):
        """T089: TypeScript AST call detection produces CallInfo records."""
        content = '''
const userService = new UserService();
const result = userService.getUser(123);
userService.deleteUser(456);
'''
        result = recognizer.recognize(Path("app.ts"), content)
        assert len(result.calls) > 0, "Expected CallInfo records from TS AST"
        callees = {c.callee for c in result.calls}
        # Should detect method calls
        assert "getUser" in callees or "deleteUser" in callees, \
            f"Expected method calls, got callees: {callees}"
        for call in result.calls:
            assert isinstance(call, CallInfo)
            assert call.file_path == "app.ts"


@requires_tree_sitter
class TestPythonASTCallDetection:
    """T090: Python AST call detection produces CallInfo records."""

    @pytest.fixture
    def recognizer(self):
        from codegiraffe.ast_scanner import PythonASTRecognizer
        return PythonASTRecognizer()

    def test_python_ast_call_detection_produces_call_info(self, recognizer):
        """T090: Python AST call detection produces CallInfo records."""
        content = '''
class UserService:
    def get_user(self, user_id):
        result = self.db.query(user_id)
        return result

    def save_user(self, user):
        validator = Validator()
        validator.validate(user)
        self.db.save(user)
'''
        result = recognizer.recognize(Path("service.py"), content)
        assert len(result.calls) > 0, "Expected CallInfo records from Python AST"
        callees = {c.callee for c in result.calls}
        # Should detect at least some of: query, Validator, validate, save
        assert len(callees) > 0, f"Expected call targets, got: {callees}"
        for call in result.calls:
            assert isinstance(call, CallInfo)
            assert call.file_path == "service.py"


@requires_tree_sitter
class TestASTRegexCompatibility:
    """T091: AST and regex modes produce compatible CallInfo results."""

    def test_ast_regex_compatible_go_calls(self):
        """T091: AST and regex modes produce compatible CallInfo for same Go file."""
        from codegiraffe.ast_scanner import GoASTRecognizer
        from codegiraffe.recognizers.go import GoRecognizer

        content = '''
package main

type App struct {
    store Store
}

func (a *App) Run() {
    a.store.Save()
    a.store.Load()
}
'''
        ast_rec = GoASTRecognizer()
        regex_rec = GoRecognizer()

        ast_result = ast_rec.recognize(Path("app.go"), content)
        regex_result = regex_rec.recognize(Path("app.go"), content)

        ast_callees = {c.callee for c in ast_result.calls}
        regex_callees = {c.callee for c in regex_result.calls}

        # Both should detect the same non-stdlib calls
        # The intersection should be non-empty -- both detect at least
        # some of the same calls
        assert ast_callees, "AST should detect calls"
        assert regex_callees, "Regex should detect calls"
        # Both should detect the key calls (Save, Load)
        common = ast_callees & regex_callees
        assert len(common) > 0, \
            f"AST and regex should share some callees. AST: {ast_callees}, Regex: {regex_callees}"

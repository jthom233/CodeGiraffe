"""Tests for language-specific recognizers."""

import pytest
from pathlib import Path

from codegiraffe.recognizers import (
    TypeScriptRecognizer,
    GoRecognizer,
    RustRecognizer,
    JavaRecognizer,
    CSharpRecognizer,
    CppRecognizer,
    PhpRecognizer,
    RubyRecognizer,
)
from codegiraffe.scanner import ScanResult, scan_project, ImportInfo, ImplementationInfo
from codegiraffe.registry import RecognizerRegistry
from codegiraffe.schema import NodeType, EdgeType


class TestTypeScriptRecognizer:
    @pytest.fixture
    def recognizer(self):
        return TypeScriptRecognizer()

    def test_express_routes(self, recognizer):
        content = '''
import express from 'express';
const app = express();
app.get("/api/users", (req, res) => { res.json([]); });
app.post("/api/users", (req, res) => { res.status(201).json({}); });
'''
        result = recognizer.recognize(Path("app.ts"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids
        assert any(n.type == NodeType.ENDPOINT for n in result.nodes)

    def test_nestjs_decorators(self, recognizer):
        content = '''
@Controller('users')
export class UsersController {
    @Get("/")
    findAll() {}
    @Post("/create")
    create() {}
}
'''
        result = recognizer.recognize(Path("users.controller.ts"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/" in ids
        assert "endpoint:/create" in ids

    def test_process_env(self, recognizer):
        content = '''
const dbUrl = process.env.DATABASE_URL;
const port = process.env["PORT"];
'''
        result = recognizer.recognize(Path("config.ts"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DATABASE_URL" in ids
        assert "env:PORT" in ids

    def test_fetch_calls(self, recognizer):
        content = '''
const res = await fetch("https://api.stripe.com/v1/charges");
await axios.post("https://api.sendgrid.com/v3/mail");
'''
        result = recognizer.recognize(Path("service.ts"), content)
        ids = {n.id for n in result.nodes}
        assert any("api.stripe.com" in nid for nid in ids)
        assert any("api.sendgrid.com" in nid for nid in ids)

    def test_react_components(self, recognizer):
        content = '''
export default function UserProfile() {
    return <div>Profile</div>;
}
export const UserList = () => {};
'''
        result = recognizer.recognize(Path("UserProfile.tsx"), content)
        ids = {n.id for n in result.nodes}
        assert any("UserProfile" in nid for nid in ids)

    def test_event_emitter(self, recognizer):
        content = '''
eventEmitter.emit("user:created");
eventEmitter.on("order:completed");
'''
        result = recognizer.recognize(Path("events.ts"), content)
        ids = {n.id for n in result.nodes}
        assert any("user:created" in nid for nid in ids)

    def test_typeorm_entity(self, recognizer):
        content = '''
@Entity("users")
export class User {
    @PrimaryGeneratedColumn()
    id: number;
}
'''
        result = recognizer.recognize(Path("user.entity.ts"), content)
        ids = {n.id for n in result.nodes}
        assert "table:users" in ids

    def test_prisma_model(self, recognizer):
        content = '''
model User {
    id    Int    @id @default(autoincrement())
    email String @unique
}
'''
        result = recognizer.recognize(Path("schema.prisma"), content)
        ids = {n.id for n in result.nodes}
        assert "table:User" in ids

    def test_bull_queue(self, recognizer):
        content = '''
const emailQueue = new Queue("email-jobs");
const worker = new Worker("email-jobs", processor);
'''
        result = recognizer.recognize(Path("queue.ts"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:email-jobs" in ids

    def test_class_fallback(self, recognizer):
        content = '''
class InternalService {
    doSomething() {}
}
'''
        result = recognizer.recognize(Path("internal.ts"), content)
        ids = {n.id for n in result.nodes}
        assert "service:InternalService" in ids

    def test_exported_class_as_component_not_service(self, recognizer):
        """Exported classes captured as components should not also appear as services."""
        content = '''
export class UserWidget {
    render() {}
}
'''
        result = recognizer.recognize(Path("widget.tsx"), content)
        ids = {n.id for n in result.nodes}
        assert "component:UserWidget" in ids
        assert "service:UserWidget" not in ids


class TestGoRecognizer:
    @pytest.fixture
    def recognizer(self):
        return GoRecognizer()

    def test_http_handlers(self, recognizer):
        content = '''
package main
import "net/http"
func main() {
    http.HandleFunc("/api/users", handleUsers)
    http.HandleFunc("/api/health", handleHealth)
}
'''
        result = recognizer.recognize(Path("main.go"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids
        assert "endpoint:/api/health" in ids

    def test_gin_routes(self, recognizer):
        content = '''
r := gin.Default()
r.GET("/api/products", getProducts)
r.POST("/api/products", createProduct)
'''
        result = recognizer.recognize(Path("router.go"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/products" in ids

    def test_os_getenv(self, recognizer):
        content = '''
dbURL := os.Getenv("DATABASE_URL")
port, ok := os.LookupEnv("PORT")
'''
        result = recognizer.recognize(Path("config.go"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DATABASE_URL" in ids
        assert "env:PORT" in ids

    def test_struct_definitions(self, recognizer):
        content = '''
type UserService struct {
    db *sql.DB
}
type PaymentHandler struct{}
'''
        result = recognizer.recognize(Path("service.go"), content)
        ids = {n.id for n in result.nodes}
        assert "service:UserService" in ids
        assert "service:PaymentHandler" in ids

    def test_gorm_models(self, recognizer):
        content = '''
type User struct {
    gorm.Model
    Name string
    Email string
}
'''
        result = recognizer.recognize(Path("models.go"), content)
        ids = {n.id for n in result.nodes}
        assert any("User" in nid for nid in ids)

    def test_http_external_call(self, recognizer):
        content = '''
resp, err := http.Get("https://api.example.com/data")
'''
        result = recognizer.recognize(Path("client.go"), content)
        ids = {n.id for n in result.nodes}
        assert any("api.example.com" in nid for nid in ids)

    def test_db_table(self, recognizer):
        content = '''
db.Table("orders").Where("status = ?", "active").Find(&orders)
'''
        result = recognizer.recognize(Path("repo.go"), content)
        ids = {n.id for n in result.nodes}
        assert "table:orders" in ids

    def test_gorm_model_not_in_service_fallback(self, recognizer):
        """GORM models should be tables, not service fallbacks."""
        content = '''
type Product struct {
    gorm.Model
    Name  string
    Price float64
}
'''
        result = recognizer.recognize(Path("models.go"), content)
        ids = {n.id for n in result.nodes}
        assert "table:Product" in ids
        assert "service:Product" not in ids

    def test_interface_definitions(self, recognizer):
        content = '''
type Store interface {
    ListConnections() ([]Connection, error)
    GetConnection(id string) (Connection, error)
    Close() error
}
'''
        result = recognizer.recognize(Path("store.go"), content)
        ids = {n.id for n in result.nodes}
        # Should create a service node with interface metadata
        assert any("Store" in nid for nid in ids)
        store_node = next(n for n in result.nodes if "Store" in n.id)
        assert store_node.metadata.get("kind") == "interface"
        # Should NOT also create a duplicate service:Store from struct fallback

    def test_internal_imports_create_edges(self, recognizer):
        content = '''
package tui

import (
    "fmt"
    "github.com/dr4zz/nexus/internal/session"
    "github.com/dr4zz/nexus/internal/config"
)

type App struct{}
'''
        result = recognizer.recognize(Path("internal/tui/app.go"), content)
        # Should have package nodes
        ids = {n.id for n in result.nodes}
        assert "pkg:tui" in ids
        # Should have dependency edges
        edge_targets = {e.target for e in result.edges}
        assert "pkg:session" in edge_targets
        assert "pkg:config" in edge_targets

    def test_bubbletea_msg_types(self, recognizer):
        content = '''
package tui

type SessionDetachedMsg struct {
    SessionID string
    ConnID    string
}

type LaunchFinishedMsg struct {
    Err error
}

type RegularStruct struct {
    Name string
}
'''
        result = recognizer.recognize(Path("messages.go"), content)
        ids = {n.id for n in result.nodes}
        types = {n.id: n.type for n in result.nodes}
        # Msg types should be event nodes
        assert "event:SessionDetachedMsg" in ids
        assert "event:LaunchFinishedMsg" in ids
        # Non-Msg structs should be service nodes
        assert "service:RegularStruct" in ids

    def test_sql_open_pattern(self, recognizer):
        content = '''
package store

import "database/sql"

func NewStore(path string) (*Store, error) {
    db, err := sql.Open("sqlite", path)
    return &Store{db: db}, err
}
'''
        result = recognizer.recognize(Path("store.go"), content)
        ids = {n.id for n in result.nodes}
        # Should detect sqlite database
        assert any("sqlite" in nid for nid in ids)

    def test_ipc_patterns(self, recognizer):
        content = '''
package ipc

import "net"

func NewServer() (*Server, error) {
    listener, err := net.Listen("unix", "/tmp/app.sock")
    return &Server{listener: listener}, err
}
'''
        result = recognizer.recognize(Path("internal/ipc/server.go"), content)
        ids = {n.id for n in result.nodes}
        # Should detect IPC server
        assert any("ipc" in nid.lower() for nid in ids)

    def test_ipc_client(self, recognizer):
        content = '''
package ipc

import "net"

func Dial() (*Client, error) {
    conn, err := net.Dial("unix", "/tmp/app.sock")
    return &Client{conn: conn}, err
}
'''
        result = recognizer.recognize(Path("internal/ipc/client.go"), content)
        ids = {n.id for n in result.nodes}
        assert any("ipc" in nid.lower() for nid in ids)

    def test_package_declaration(self, recognizer):
        content = '''
package launcher

type SSHLauncher struct {
    host string
}
'''
        result = recognizer.recognize(Path("internal/launcher/ssh.go"), content)
        ids = {n.id for n in result.nodes}
        assert "pkg:launcher" in ids

    def test_service_env_var_edge(self, recognizer):
        content = '''
package config

type Config struct {
    Path string
}

func Load() (*Config, error) {
    dir := os.Getenv("XDG_CONFIG_HOME")
    return &Config{Path: dir}, nil
}
'''
        result = recognizer.recognize(Path("config.go"), content)
        # Should have edge from package to env var
        edge_pairs = {(e.source, e.target) for e in result.edges}
        assert any("env:XDG_CONFIG_HOME" in target for _, target in edge_pairs)

    def test_interface_not_duplicated_as_struct(self, recognizer):
        """Interfaces should NOT also create a service node from struct fallback."""
        content = '''
type Vault interface {
    Get(id string) (string, error)
    Set(id string, credential string) error
}
'''
        result = recognizer.recognize(Path("vault.go"), content)
        ids = [n.id for n in result.nodes]
        # Should only have one node for Vault, not two
        vault_nodes = [nid for nid in ids if "Vault" in nid]
        assert len(vault_nodes) == 1

    def test_msg_not_duplicated_as_service(self, recognizer):
        """Msg types should be events, not also services."""
        content = '''
type TickMsg struct{}
'''
        result = recognizer.recognize(Path("health.go"), content)
        ids = {n.id for n in result.nodes}
        assert "event:TickMsg" in ids
        assert "service:TickMsg" not in ids


class TestGoRecognizerImports:
    """Tests for Go recognizer v0.6.0 import parsing and classification."""

    @pytest.fixture
    def recognizer(self):
        return GoRecognizer()

    def test_parse_imports_single_line(self, recognizer):
        """Single-line import statement should be extracted."""
        content = '''
package main

import "fmt"

func main() {}
'''
        imports = recognizer._parse_imports(content)
        assert imports == ["fmt"]

    def test_parse_imports_grouped(self, recognizer):
        """Grouped import block should extract all paths."""
        content = '''
package main

import (
    "fmt"
    "os"
)

func main() {}
'''
        imports = recognizer._parse_imports(content)
        assert "fmt" in imports
        assert "os" in imports
        assert len(imports) == 2

    def test_is_internal_import_true(self, recognizer, tmp_path):
        """Internal imports matching the go.mod module path should return True."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module github.com/myorg/myproject\n\ngo 1.21\n")
        recognizer.set_project_root(str(tmp_path))
        assert recognizer._is_internal_import("github.com/myorg/myproject/internal/store") is True
        assert recognizer._is_internal_import("github.com/myorg/myproject/pkg/utils") is True

    def test_is_internal_import_false_stdlib(self, recognizer, tmp_path):
        """Standard library and third-party imports should return False."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module github.com/myorg/myproject\n\ngo 1.21\n")
        recognizer.set_project_root(str(tmp_path))
        assert recognizer._is_internal_import("fmt") is False
        assert recognizer._is_internal_import("os") is False
        assert recognizer._is_internal_import("net/http") is False
        assert recognizer._is_internal_import("github.com/gin-gonic/gin") is False

    def test_import_to_module_path(self, recognizer, tmp_path):
        """Go import paths should be converted to dotted module paths."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module github.com/myorg/myproject\n\ngo 1.21\n")
        recognizer.set_project_root(str(tmp_path))
        result = recognizer._import_to_module_path("github.com/myorg/myproject/internal/store")
        assert result == "internal.store"
        result2 = recognizer._import_to_module_path("github.com/myorg/myproject/pkg/utils/log")
        assert result2 == "pkg.utils.log"

    def test_recognize_returns_import_info_for_internal(self, recognizer, tmp_path):
        """recognize() should return ImportInfo for internal imports when project root is set."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module github.com/myorg/myproject\n\ngo 1.21\n")
        recognizer.set_project_root(str(tmp_path))

        content = '''
package main

import (
    "fmt"
    "github.com/myorg/myproject/internal/store"
    "github.com/myorg/myproject/pkg/config"
)

func main() {}
'''
        result = recognizer.recognize(Path("cmd/main.go"), content)
        assert len(result.imports) == 2
        module_paths = {imp.module_path for imp in result.imports}
        assert "internal.store" in module_paths
        assert "pkg.config" in module_paths
        # All should be absolute style
        assert all(imp.style == "absolute" for imp in result.imports)
        # Go imports entire packages, so symbols should be empty
        assert all(imp.symbols == [] for imp in result.imports)

    def test_recognize_no_import_info_for_stdlib(self, recognizer, tmp_path):
        """recognize() should NOT return ImportInfo for stdlib imports."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module github.com/myorg/myproject\n\ngo 1.21\n")
        recognizer.set_project_root(str(tmp_path))

        content = '''
package main

import (
    "fmt"
    "os"
    "net/http"
)

func main() {}
'''
        result = recognizer.recognize(Path("main.go"), content)
        assert len(result.imports) == 0


class TestGoRecognizerImplementations:
    """Tests for Go recognizer v0.6.0 interface implementation detection."""

    @pytest.fixture
    def recognizer(self):
        return GoRecognizer()

    def test_struct_implementing_interface(self, recognizer):
        """A struct with methods matching an interface should produce ImplementationInfo."""
        content = '''
package store

type Repository interface {
    Get(id string) (Item, error)
    Save(item Item) error
}

type SQLRepository struct {
    db *sql.DB
}

func (r *SQLRepository) Get(id string) (Item, error) {
    return Item{}, nil
}

func (r *SQLRepository) Save(item Item) error {
    return nil
}
'''
        result = recognizer.recognize(Path("store.go"), content)
        assert len(result.implementations) == 1
        impl = result.implementations[0]
        assert impl.child_class == "SQLRepository"
        assert impl.parent_class == "Repository"
        assert impl.file_path == "store.go"

    def test_struct_not_implementing_all_methods(self, recognizer):
        """A struct missing interface methods should NOT produce ImplementationInfo."""
        content = '''
package store

type Repository interface {
    Get(id string) (Item, error)
    Save(item Item) error
    Delete(id string) error
}

type PartialRepo struct {
    db *sql.DB
}

func (r *PartialRepo) Get(id string) (Item, error) {
    return Item{}, nil
}
'''
        result = recognizer.recognize(Path("store.go"), content)
        assert len(result.implementations) == 0


class TestRustRecognizer:
    @pytest.fixture
    def recognizer(self):
        return RustRecognizer()

    def test_actix_routes(self, recognizer):
        content = '''
#[get("/api/users")]
async fn get_users() -> impl Responder {}

#[post("/api/users")]
async fn create_user() -> impl Responder {}
'''
        result = recognizer.recognize(Path("handlers.rs"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids

    def test_env_var(self, recognizer):
        content = '''
let db_url = env::var("DATABASE_URL").unwrap();
let port = std::env::var("PORT").unwrap_or("8080".to_string());
'''
        result = recognizer.recognize(Path("config.rs"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DATABASE_URL" in ids
        assert "env:PORT" in ids

    def test_struct_definitions(self, recognizer):
        content = '''
pub struct AppState {
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

    def test_diesel_table(self, recognizer):
        content = '''
table! {
    users (id) {
        id -> Int4,
        name -> Varchar,
    }
}
#[derive(Queryable)]
pub struct User {
    pub id: i32,
    pub name: String,
}
'''
        result = recognizer.recognize(Path("schema.rs"), content)
        ids = {n.id for n in result.nodes}
        assert any("users" in nid for nid in ids)

    def test_route_call(self, recognizer):
        content = '''
App::new()
    .route("/api/items", web::get().to(get_items))
    .route("/api/items", web::post().to(create_item))
'''
        result = recognizer.recognize(Path("main.rs"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/items" in ids

    def test_env_macro(self, recognizer):
        content = '''
let api_key = env!("API_KEY");
'''
        result = recognizer.recognize(Path("lib.rs"), content)
        ids = {n.id for n in result.nodes}
        assert "env:API_KEY" in ids

    def test_reqwest_external_call(self, recognizer):
        content = '''
let body = reqwest::get("https://httpbin.org/ip").await?.text().await?;
'''
        result = recognizer.recognize(Path("client.rs"), content)
        ids = {n.id for n in result.nodes}
        assert any("httpbin.org" in nid for nid in ids)

    def test_queryable_struct_not_in_service_fallback(self, recognizer):
        """Queryable structs should be tables, not service fallbacks."""
        content = '''
#[derive(Queryable)]
pub struct Post {
    pub id: i32,
    pub title: String,
}
'''
        result = recognizer.recognize(Path("models.rs"), content)
        ids = {n.id for n in result.nodes}
        assert "table:Post" in ids
        assert "service:Post" not in ids


class TestJavaRecognizer:
    @pytest.fixture
    def recognizer(self):
        return JavaRecognizer()

    def test_spring_mappings(self, recognizer):
        content = '''
@RestController
@RequestMapping("/api")
public class UserController {
    @GetMapping("/users")
    public List<User> getUsers() {}

    @PostMapping("/users")
    public User createUser() {}
}
'''
        result = recognizer.recognize(Path("UserController.java"), content)
        ids = {n.id for n in result.nodes}
        assert any("/users" in nid for nid in ids)

    def test_jpa_entity(self, recognizer):
        content = '''
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
        assert any("users" in nid for nid in ids)

    def test_system_getenv(self, recognizer):
        content = '''
String dbUrl = System.getenv("DATABASE_URL");
@Value("${server.port}")
private int port;
'''
        result = recognizer.recognize(Path("Config.java"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DATABASE_URL" in ids

    def test_kafka_listener(self, recognizer):
        content = '''
@KafkaListener(topics = "orders")
public void processOrder(Order order) {}

@RabbitListener(queues = "notifications")
public void handleNotification(Notification n) {}
'''
        result = recognizer.recognize(Path("Listener.java"), content)
        ids = {n.id for n in result.nodes}
        assert any("orders" in nid for nid in ids)
        assert any("notifications" in nid for nid in ids)

    def test_class_definitions(self, recognizer):
        content = '''
public class PaymentService {
    // ...
}
class InternalHelper {
    // ...
}
'''
        result = recognizer.recognize(Path("PaymentService.java"), content)
        ids = {n.id for n in result.nodes}
        assert "service:PaymentService" in ids

    def test_request_mapping(self, recognizer):
        content = '''
@RequestMapping("/api/health")
public String health() { return "ok"; }
'''
        result = recognizer.recognize(Path("HealthController.java"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/health" in ids

    def test_value_annotation(self, recognizer):
        content = '''
@Value("${spring.datasource.url}")
private String datasourceUrl;
'''
        result = recognizer.recognize(Path("DbConfig.java"), content)
        ids = {n.id for n in result.nodes}
        assert "env:spring.datasource.url" in ids

    def test_entity_without_table_annotation(self, recognizer):
        """@Entity without @Table should use class name."""
        content = '''
@Entity
public class Order {
    @Id
    private Long id;
}
'''
        result = recognizer.recognize(Path("Order.java"), content)
        ids = {n.id for n in result.nodes}
        assert "table:Order" in ids


class TestScanProjectMultiLanguage:
    def test_scan_project_with_typescript(self, tmp_path):
        (tmp_path / "app.ts").write_text('''
import express from 'express';
const app = express();
app.get("/api/users", handler);
const dbUrl = process.env.DATABASE_URL;
''')
        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids
        assert "env:DATABASE_URL" in ids

    def test_scan_project_with_go(self, tmp_path):
        (tmp_path / "main.go").write_text('''
package main
import "net/http"
func main() {
    http.HandleFunc("/api/health", healthCheck)
    port := os.Getenv("PORT")
}
''')
        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/health" in ids
        assert "env:PORT" in ids

    def test_scan_project_with_rust(self, tmp_path):
        (tmp_path / "main.rs").write_text('''
#[get("/api/status")]
async fn status() -> impl Responder {}

let db = env::var("DB_HOST").unwrap();
''')
        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/status" in ids
        assert "env:DB_HOST" in ids

    def test_scan_project_with_java(self, tmp_path):
        (tmp_path / "App.java").write_text('''
@RestController
public class App {
    @GetMapping("/api/info")
    public String info() { return "ok"; }
}
''')
        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/info" in ids

    def test_scan_project_mixed_languages(self, tmp_path):
        (tmp_path / "app.py").write_text('''
from flask import Flask
app = Flask(__name__)
@app.route("/api/python")
def python_endpoint():
    pass
''')
        (tmp_path / "app.ts").write_text('''
app.get("/api/typescript", handler);
''')
        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/python" in ids
        assert "endpoint:/api/typescript" in ids

    def test_scan_project_with_csharp(self, tmp_path):
        (tmp_path / "Controller.cs").write_text('''
[HttpGet("/api/items")]
public IActionResult Get() { return Ok(); }
var key = Environment.GetEnvironmentVariable("API_KEY");
''')
        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/items" in ids
        assert "env:API_KEY" in ids

    def test_scan_project_with_cpp(self, tmp_path):
        (tmp_path / "main.cpp").write_text('''
#include "mylib.h"
const char *host = getenv("HOST");
struct Server { int fd; };
''')
        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "env:HOST" in ids
        assert "service:Server" in ids

    def test_scan_project_with_php(self, tmp_path):
        (tmp_path / "routes.php").write_text("""
Route::get('/api/products', 'ProductController@index');
$key = env('APP_KEY');
""")
        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/products" in ids
        assert "env:APP_KEY" in ids

    def test_scan_project_with_ruby(self, tmp_path):
        (tmp_path / "routes.rb").write_text("""
get '/api/health'
""")
        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/health" in ids

    def test_scan_project_all_languages(self, tmp_path):
        """Verify all language recognizers are scanned in one project."""
        (tmp_path / "server.ts").write_text('app.get("/ts-route", h);')
        (tmp_path / "main.go").write_text('http.HandleFunc("/go-route", h)')
        (tmp_path / "main.rs").write_text('#[get("/rs-route")]\nasync fn h() {}')
        (tmp_path / "App.java").write_text('@GetMapping("/java-route")\npublic void h() {}')
        (tmp_path / "Controller.cs").write_text('[HttpGet("/cs-route")]\npublic void H() {}')
        (tmp_path / "routes.php").write_text("Route::get('/php-route', 'C@i');")
        (tmp_path / "routes.rb").write_text("get '/rb-route'")

        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/ts-route" in ids
        assert "endpoint:/go-route" in ids
        assert "endpoint:/rs-route" in ids
        assert "endpoint:/java-route" in ids
        assert "endpoint:/cs-route" in ids
        assert "endpoint:/php-route" in ids
        assert "endpoint:/rb-route" in ids


class TestDefaultRegistryExtensions:
    """Verify the default registry includes all expected extensions."""

    def test_default_registry_has_all_extensions(self):
        from codegiraffe.registry import get_default_registry

        registry = get_default_registry()
        extensions = registry.registered_extensions
        for ext in [
            ".py", ".pyi", ".ts", ".tsx", ".mts", ".cts", ".go", ".rs", ".java",
            ".cs", ".c", ".cpp", ".h", ".hpp", ".cc", ".cxx", ".php", ".rb",
        ]:
            assert ext in extensions, f"Missing extension: {ext}"


class TestCSharpRecognizer:
    @pytest.fixture
    def recognizer(self):
        return CSharpRecognizer()

    def test_aspnet_route_attributes(self, recognizer):
        content = '''
[HttpGet("/api/users")]
public async Task<IActionResult> GetUsers() { return Ok(); }

[HttpPost("/api/users")]
public async Task<IActionResult> CreateUser() { return Created(); }
'''
        result = recognizer.recognize(Path("Controllers/UsersController.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids
        assert any(n.type == "endpoint" for n in result.nodes)

    def test_route_attribute(self, recognizer):
        content = '''
[Route("api/health")]
public string Health() { return "ok"; }
'''
        result = recognizer.recognize(Path("Controllers/HealthController.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:api/health" in ids

    def test_entity_framework_table(self, recognizer):
        content = '''
[Table("Orders")]
public class Order { public int Id { get; set; } }
'''
        result = recognizer.recognize(Path("Models/Order.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "table:Orders" in ids

    def test_entity_framework_dbset(self, recognizer):
        content = '''
public class AppDbContext : DbContext {
    public DbSet<User> Users { get; set; }
    public DbSet<Order> Orders { get; set; }
}
'''
        result = recognizer.recognize(Path("Data/AppDbContext.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "table:User" in ids
        assert "table:Order" in ids

    def test_environment_variable(self, recognizer):
        content = '''
var dbHost = Environment.GetEnvironmentVariable("DB_HOST");
'''
        result = recognizer.recognize(Path("Config.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DB_HOST" in ids

    def test_httpclient_external_api(self, recognizer):
        content = '''
await _httpClient.PostAsync("https://api.stripe.com/v1/charges");
'''
        result = recognizer.recognize(Path("Services/PaymentService.cs"), content)
        ids = {n.id for n in result.nodes}
        assert any("api.stripe.com" in nid for nid in ids)

    def test_signalr_hub(self, recognizer):
        content = '''
public class ChatHub : Hub<IChatClient> {
    public async Task SendMessage(string msg) { }
}
'''
        result = recognizer.recognize(Path("Hubs/ChatHub.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "service:ChatHub" in ids
        hub_node = next(n for n in result.nodes if n.id == "service:ChatHub")
        assert hub_node.metadata.get("kind") == "signalr_hub"

    def test_mediatr_handler(self, recognizer):
        content = '''
public class CreateOrderHandler : IRequestHandler<CreateOrderCommand, int> {
    public Task<int> Handle(CreateOrderCommand request, CancellationToken ct) { return Task.FromResult(1); }
}
'''
        result = recognizer.recognize(Path("Handlers/CreateOrderHandler.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:CreateOrderHandler" in ids

    def test_di_registration(self, recognizer):
        content = '''
services.AddScoped<IOrderService>();
services.AddSingleton<ICacheService>();
'''
        result = recognizer.recognize(Path("Startup.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "service:IOrderService" in ids
        assert "service:ICacheService" in ids

    def test_class_fallback(self, recognizer):
        content = '''
internal class HelperUtil { }
'''
        result = recognizer.recognize(Path("Helpers/HelperUtil.cs"), content)
        ids = {n.id for n in result.nodes}
        assert "service:HelperUtil" in ids

    def test_signalr_hub_not_duplicated_as_service(self, recognizer):
        """SignalR hubs should not also appear as fallback services."""
        content = '''
public class NotificationHub : Hub {
    public async Task Notify(string msg) { }
}
'''
        result = recognizer.recognize(Path("Hubs/NotificationHub.cs"), content)
        ids = [n.id for n in result.nodes]
        hub_nodes = [nid for nid in ids if "NotificationHub" in nid]
        assert len(hub_nodes) == 1


class TestCppRecognizer:
    @pytest.fixture
    def recognizer(self):
        return CppRecognizer()

    def test_local_include(self, recognizer):
        content = '''
#include "mylib.h"
#include "utils/helper.h"
'''
        result = recognizer.recognize(Path("src/main.cpp"), content)
        ids = {n.id for n in result.nodes}
        assert "service:mylib" in ids
        assert "service:helper" in ids

    def test_system_include_ignored(self, recognizer):
        content = '''
#include <stdio.h>
#include <vector>
'''
        result = recognizer.recognize(Path("main.cpp"), content)
        ids = {n.id for n in result.nodes}
        # System includes should NOT produce nodes
        assert not any("stdio" in nid for nid in ids)

    def test_struct_definition(self, recognizer):
        content = '''
struct Connection {
    int fd;
    char *host;
};
'''
        result = recognizer.recognize(Path("network.h"), content)
        ids = {n.id for n in result.nodes}
        assert "service:Connection" in ids

    def test_class_definition(self, recognizer):
        content = '''
class HttpServer : public BaseServer {
    void handle();
};
'''
        result = recognizer.recognize(Path("server.h"), content)
        ids = {n.id for n in result.nodes}
        assert "service:HttpServer" in ids

    def test_socket_pattern(self, recognizer):
        content = '''
int fd = socket(AF_INET, SOCK_STREAM, 0);
bind(fd, (struct sockaddr *)&addr, sizeof(addr));
'''
        result = recognizer.recognize(Path("src/server.cpp"), content)
        ids = {n.id for n in result.nodes}
        assert any("socket" in nid for nid in ids)
        assert any(n.type == "queue" for n in result.nodes)

    def test_getenv(self, recognizer):
        content = '''
const char *host = getenv("SERVER_HOST");
const char *port = getenv("SERVER_PORT");
'''
        result = recognizer.recognize(Path("config.c"), content)
        ids = {n.id for n in result.nodes}
        assert "env:SERVER_HOST" in ids
        assert "env:SERVER_PORT" in ids

    def test_curl_external_api(self, recognizer):
        content = '''
curl_easy_setopt(curl, CURLOPT_URL, "https://api.example.com/data");
'''
        result = recognizer.recognize(Path("client.c"), content)
        ids = {n.id for n in result.nodes}
        assert any("api.example.com" in nid for nid in ids)

    def test_function_definition(self, recognizer):
        content = '''
void process_request(int fd) {
    // do stuff
}
'''
        result = recognizer.recognize(Path("handler.c"), content)
        ids = {n.id for n in result.nodes}
        assert "service:process_request" in ids

    def test_control_flow_excluded(self, recognizer):
        content = '''
void main() {
    if (x > 0) {
        return;
    }
    while (running) {
        // loop
    }
}
'''
        result = recognizer.recognize(Path("main.c"), content)
        ids = {n.id for n in result.nodes}
        # 'if', 'while', 'return' should NOT be captured as functions
        assert "service:if" not in ids
        assert "service:while" not in ids

    def test_define_macro(self, recognizer):
        content = '''
#define MAX_BUFFER_SIZE 1024
#define APP_VERSION "1.0.0"
'''
        result = recognizer.recognize(Path("config.h"), content)
        ids = {n.id for n in result.nodes}
        assert "config:MAX_BUFFER_SIZE" in ids
        assert "config:APP_VERSION" in ids

    def test_include_guard_excluded(self, recognizer):
        content = '''
#ifndef MY_HEADER_H_
#define MY_HEADER_H_
#endif
'''
        result = recognizer.recognize(Path("header.h"), content)
        ids = {n.id for n in result.nodes}
        assert "config:MY_HEADER_H_" not in ids


class TestPhpRecognizer:
    @pytest.fixture
    def recognizer(self):
        return PhpRecognizer()

    def test_laravel_routes(self, recognizer):
        content = """
Route::get('/api/users', 'UserController@index');
Route::post('/api/users', 'UserController@store');
"""
        result = recognizer.recognize(Path("routes/api.php"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids

    def test_symfony_route_attribute(self, recognizer):
        content = """
#[Route('/api/products')]
public function index(): Response { }
"""
        result = recognizer.recognize(Path("src/Controller/ProductController.php"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/products" in ids

    def test_eloquent_model(self, recognizer):
        content = """
class UserProfile extends Model {
    protected $fillable = ['name', 'email'];
}
"""
        result = recognizer.recognize(Path("app/Models/UserProfile.php"), content)
        ids = {n.id for n in result.nodes}
        assert "table:user_profiles" in ids

    def test_eloquent_explicit_table(self, recognizer):
        content = """
class Item extends Model {
    protected $table = 'inventory_items';
}
"""
        result = recognizer.recognize(Path("app/Models/Item.php"), content)
        ids = {n.id for n in result.nodes}
        assert "table:inventory_items" in ids

    def test_env_calls(self, recognizer):
        content = """
$dbUrl = env('DATABASE_URL');
$port = getenv('PORT');
$secret = $_ENV['SECRET_KEY'];
"""
        result = recognizer.recognize(Path("config/app.php"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DATABASE_URL" in ids
        assert "env:PORT" in ids
        assert "env:SECRET_KEY" in ids

    def test_queue_job(self, recognizer):
        content = """
class SendEmailJob extends Job implements ShouldQueue {
    public function handle() { }
}
"""
        result = recognizer.recognize(Path("app/Jobs/SendEmailJob.php"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:SendEmailJob" in ids

    def test_http_facade(self, recognizer):
        content = """
$response = Http::post('https://api.stripe.com/v1/charges');
"""
        result = recognizer.recognize(Path("app/Services/PaymentService.php"), content)
        ids = {n.id for n in result.nodes}
        assert any("api.stripe.com" in nid for nid in ids)

    def test_class_fallback(self, recognizer):
        content = """
class PaymentService {
    public function charge($amount) { }
}
"""
        result = recognizer.recognize(Path("app/Services/PaymentService.php"), content)
        ids = {n.id for n in result.nodes}
        assert "service:PaymentService" in ids

    def test_eloquent_model_not_duplicated_as_service(self, recognizer):
        """Eloquent models should be tables, not also service fallbacks."""
        content = """
class Order extends Model {
    protected $fillable = ['total'];
}
"""
        result = recognizer.recognize(Path("app/Models/Order.php"), content)
        ids = {n.id for n in result.nodes}
        assert any("table:" in nid for nid in ids)
        assert "service:Order" not in ids

    def test_queue_job_not_duplicated_as_service(self, recognizer):
        """Queue jobs should be workers, not also service fallbacks."""
        content = """
class ProcessPayment extends Job implements ShouldQueue {
    public function handle() { }
}
"""
        result = recognizer.recognize(Path("app/Jobs/ProcessPayment.php"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:ProcessPayment" in ids
        assert "service:ProcessPayment" not in ids


class TestRubyRecognizer:
    @pytest.fixture
    def recognizer(self):
        return RubyRecognizer()

    def test_rails_routes(self, recognizer):
        content = """
get '/api/users'
post '/api/sessions'
"""
        result = recognizer.recognize(Path("config/routes.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/api/users" in ids
        assert "endpoint:/api/sessions" in ids

    def test_resource_routes(self, recognizer):
        content = """
resources :orders
resource :profile
"""
        result = recognizer.recognize(Path("config/routes.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "endpoint:/orders" in ids
        assert "endpoint:/profile" in ids

    def test_activerecord_model(self, recognizer):
        content = """
class UserProfile < ApplicationRecord
  has_many :orders
end
"""
        result = recognizer.recognize(Path("app/models/user_profile.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "table:user_profiles" in ids

    def test_activerecord_base(self, recognizer):
        content = """
class Order < ActiveRecord::Base
  belongs_to :user
end
"""
        result = recognizer.recognize(Path("app/models/order.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "table:orders" in ids

    def test_sidekiq_worker(self, recognizer):
        content = """
class EmailWorker
  include Sidekiq::Worker

  def perform(user_id)
  end
end
"""
        result = recognizer.recognize(Path("app/workers/email_worker.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:EmailWorker" in ids

    def test_sidekiq_job(self, recognizer):
        content = """
class NotificationJob
  include Sidekiq::Job

  def perform(msg)
  end
end
"""
        result = recognizer.recognize(Path("app/jobs/notification_job.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:NotificationJob" in ids

    def test_env_access(self, recognizer):
        content = """
db_url = ENV['DATABASE_URL']
secret = ENV.fetch('SECRET_KEY')
redis = ENV["REDIS_URL"]
"""
        result = recognizer.recognize(Path("config/application.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "env:DATABASE_URL" in ids
        assert "env:SECRET_KEY" in ids
        assert "env:REDIS_URL" in ids

    def test_http_calls(self, recognizer):
        content = """
response = Net::HTTP.get(URI('https://api.example.com/data'))
result = HTTParty.get('https://hooks.slack.com/services/abc')
"""
        result = recognizer.recognize(Path("app/services/api_client.rb"), content)
        ids = {n.id for n in result.nodes}
        assert any("api.example.com" in nid for nid in ids)
        assert any("hooks.slack.com" in nid for nid in ids)

    def test_class_fallback(self, recognizer):
        content = """
class PaymentService
  def charge(amount)
  end
end
"""
        result = recognizer.recognize(Path("app/services/payment_service.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "service:PaymentService" in ids

    def test_activerecord_model_not_duplicated_as_service(self, recognizer):
        """ActiveRecord models should be tables, not also service fallbacks."""
        content = """
class Product < ApplicationRecord
  has_many :reviews
end
"""
        result = recognizer.recognize(Path("app/models/product.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "table:products" in ids
        assert "service:Product" not in ids

    def test_sidekiq_worker_not_duplicated_as_service(self, recognizer):
        """Sidekiq workers should not also appear as fallback services."""
        content = """
class ReportWorker
  include Sidekiq::Worker

  def perform
  end
end
"""
        result = recognizer.recognize(Path("app/workers/report_worker.rb"), content)
        ids = {n.id for n in result.nodes}
        assert "worker:ReportWorker" in ids
        assert "service:ReportWorker" not in ids


# ---------------------------------------------------------------------------
# Phase 5 (v0.9.0): Implements-detection edge-case tests
# ---------------------------------------------------------------------------


class TestTypeScriptImplementsEdgeCases:
    """T099-T101: Verify TypeScript implements detection edge cases."""

    @pytest.fixture
    def recognizer(self):
        return TypeScriptRecognizer()

    def test_multi_interface_implements(self, recognizer):
        """T099: class Foo implements Bar, Baz produces 2 ImplementationInfo records."""
        content = '''
class Foo implements Bar, Baz {
    doSomething() {}
}
'''
        result = recognizer.recognize(Path("foo.ts"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        assert ("Foo", "Bar") in impl_map
        assert ("Foo", "Baz") in impl_map
        impl_for_foo = [i for i in result.implementations if i.child_class == "Foo"]
        assert len(impl_for_foo) >= 2

    def test_generic_interface_stripped(self, recognizer):
        """T100: class Foo implements Bar<string> produces ImplementationInfo(parent_class="Bar")."""
        content = '''
class Foo implements Bar<string> {
    doSomething() {}
}
'''
        result = recognizer.recognize(Path("foo.ts"), content)
        impl_parents = [i.parent_class for i in result.implementations if i.child_class == "Foo"]
        assert "Bar" in impl_parents

    def test_extends_and_implements(self, recognizer):
        """T101: class Foo extends Base implements Bar produces both extends and implements."""
        content = '''
class Foo extends Base implements Bar {
    doSomething() {}
}
'''
        result = recognizer.recognize(Path("foo.ts"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        # extends Base
        assert ("Foo", "Base") in impl_map
        # implements Bar
        assert ("Foo", "Bar") in impl_map


class TestJavaImplementsEdgeCases:
    """T102: Verify Java multi-interface implements detection."""

    @pytest.fixture
    def recognizer(self):
        return JavaRecognizer()

    def test_multi_interface_implements(self, recognizer):
        """T102: class Foo implements Bar, Baz produces 2 ImplementationInfo records."""
        content = '''
public class Foo implements Bar, Baz {
    public void doSomething() {}
}
'''
        result = recognizer.recognize(Path("Foo.java"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        assert ("Foo", "Bar") in impl_map
        assert ("Foo", "Baz") in impl_map
        impl_for_foo = [i for i in result.implementations if i.child_class == "Foo"]
        assert len(impl_for_foo) >= 2


class TestCSharpImplementsEdgeCases:
    """T103: Verify C# base class vs interface disambiguation."""

    @pytest.fixture
    def recognizer(self):
        return CSharpRecognizer()

    def test_base_class_and_interface_distinction(self, recognizer):
        """T103: class Foo : BaseClass, IInterface distinguishes base class from interface."""
        content = '''
public class Foo : BaseClass, IInterface {
    public void DoSomething() {}
}
'''
        result = recognizer.recognize(Path("Foo.cs"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        # Both should appear as ImplementationInfo entries
        assert ("Foo", "BaseClass") in impl_map
        assert ("Foo", "IInterface") in impl_map


class TestRustImplTraitEdgeCases:
    """T106: Verify Rust impl Trait for Struct basic case."""

    @pytest.fixture
    def recognizer(self):
        return RustRecognizer()

    def test_impl_trait_for_struct(self, recognizer):
        """T106: impl Display for MyStruct produces correct ImplementationInfo."""
        content = '''
pub struct MyStruct {
    pub name: String,
}

impl Display for MyStruct {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{}", self.name)
    }
}
'''
        result = recognizer.recognize(Path("my_struct.rs"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        assert ("MyStruct", "Display") in impl_map


class TestPhpImplementsEdgeCases:
    """T108: Verify PHP multi-interface implements."""

    @pytest.fixture
    def recognizer(self):
        return PhpRecognizer()

    def test_multi_interface_implements(self, recognizer):
        """T108: class Foo implements Bar, Baz produces 2 ImplementationInfo records."""
        content = """
class Foo implements Bar, Baz {
    public function doSomething() {}
}
"""
        result = recognizer.recognize(Path("Foo.php"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        assert ("Foo", "Bar") in impl_map
        assert ("Foo", "Baz") in impl_map


class TestRubyImplementsEdgeCases:
    """T108: Verify Ruby include Module detection."""

    @pytest.fixture
    def recognizer(self):
        return RubyRecognizer()

    def test_class_inheritance(self, recognizer):
        """T108: class Foo < Bar produces ImplementationInfo."""
        content = """
class Foo < CustomBase
  def do_something
  end
end
"""
        result = recognizer.recognize(Path("foo.rb"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        assert ("Foo", "CustomBase") in impl_map

    def test_external_base_excluded(self, recognizer):
        """External bases like ApplicationRecord should be excluded."""
        content = """
class User < ApplicationRecord
  has_many :orders
end
"""
        result = recognizer.recognize(Path("user.rb"), content)
        impl_for_user = [i for i in result.implementations if i.child_class == "User"]
        assert len(impl_for_user) == 0


class TestCppInheritanceEdgeCases:
    """T109: Verify C++ class Foo : public IBar."""

    @pytest.fixture
    def recognizer(self):
        return CppRecognizer()

    def test_public_inheritance(self, recognizer):
        """T109: class Foo : public IBar produces ImplementationInfo."""
        content = '''
class Foo : public IBar {
    void handle() override;
};
'''
        result = recognizer.recognize(Path("foo.h"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        assert ("Foo", "IBar") in impl_map

    def test_multiple_inheritance(self, recognizer):
        """T109: class Foo : public IBar, public IBaz produces 2 ImplementationInfo records."""
        content = '''
class Foo : public IBar, public IBaz {
    void handle() override;
};
'''
        result = recognizer.recognize(Path("foo.h"), content)
        impl_map = {(i.child_class, i.parent_class) for i in result.implementations}
        assert ("Foo", "IBar") in impl_map
        assert ("Foo", "IBaz") in impl_map

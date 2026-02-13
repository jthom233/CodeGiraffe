"""Tests for language-specific recognizers."""

import pytest
from pathlib import Path

from codegiraffe.recognizers import (
    TypeScriptRecognizer,
    GoRecognizer,
    RustRecognizer,
    JavaRecognizer,
)
from codegiraffe.scanner import ScanResult, scan_project
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

    def test_scan_project_all_four_languages(self, tmp_path):
        """Verify all four new languages are scanned in one project."""
        (tmp_path / "server.ts").write_text('app.get("/ts-route", h);')
        (tmp_path / "main.go").write_text('http.HandleFunc("/go-route", h)')
        (tmp_path / "main.rs").write_text('#[get("/rs-route")]\nasync fn h() {}')
        (tmp_path / "App.java").write_text('@GetMapping("/java-route")\npublic void h() {}')

        result = scan_project(str(tmp_path))
        ids = {n.id for n in result.nodes}
        assert "endpoint:/ts-route" in ids
        assert "endpoint:/go-route" in ids
        assert "endpoint:/rs-route" in ids
        assert "endpoint:/java-route" in ids


class TestDefaultRegistryExtensions:
    """Verify the default registry includes all expected extensions."""

    def test_default_registry_has_all_extensions(self):
        from codegiraffe.registry import get_default_registry

        registry = get_default_registry()
        extensions = registry.registered_extensions
        for ext in [".py", ".pyi", ".ts", ".tsx", ".mts", ".cts", ".go", ".rs", ".java"]:
            assert ext in extensions, f"Missing extension: {ext}"

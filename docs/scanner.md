[← Back to Documentation](README.md)

# Multi-Language Scanner

Code Giraffe uses a plugin-based scanner architecture built on the `RecognizerRegistry`. Each language has a dedicated recognizer that detects framework-specific patterns, producing typed graph nodes and edges. The Python recognizer is built into the core scanner; all other languages are provided by recognizer plugins registered by file extension.

By default the scanner uses regex matching for speed. For higher accuracy via actual syntax trees, see [AST-Aware Scanning](#ast-aware-scanning) below.

---

## Scanner Intelligence

The scanner includes several intelligence features introduced across v0.4.0 through v0.9.0. These produce a richer, more accurate architecture graph beyond raw endpoint/table detection.

**Test file exclusion** — Test files are excluded from scans by default across all languages. Pass `include_tests=true` to `codegiraffe_init` or `codegiraffe_sync` to include them. Test-sourced nodes are tagged with `"source": "test"` metadata.

| Language | Test file patterns excluded |
|---|---|
| Python | `test_*.py`, `*_test.py`, `conftest.py` |
| Go | `*_test.go` |
| Java | `*Test.java` |
| Rust | test modules |
| TypeScript | `*.spec.ts`, `*.test.ts` |

**Module nodes** — Each source file produces a `module` node (e.g., `mod:codegiraffe.scanner` for Python, `mod:github.com/user/pkg` for Go) with `contains` edges to every entity defined in that file.

**Import detection** — The scanner detects import statements in all 9 languages, resolves them to project-internal modules (skipping standard library and third-party dependencies), and creates `imports` edges between `module` nodes with metadata listing the imported symbols. Go uses `go.mod`-aware module path resolution.

**Inheritance / implementation detection** — Class definitions with base classes (or interface implementations in Go) produce `implements` edges from child to parent when both are defined within the project. External base classes are silently skipped. Go interface satisfaction is detected via duck-type method set matching across files.

**Call-graph edges (v0.9.0)** — The scanner detects function and method calls in Go, Python, and TypeScript (via both regex and tree-sitter AST when available), creating `calls` edges between service/module nodes. Demand-driven method nodes (e.g., `service:Parent.Method`) are created for call-graph participants. The `_infer_call_edges()` pipeline step resolves callee names to graph nodes and produces typed edges.

### Feature Matrix

| Language | Module Nodes | Import Detection | Implementation Detection | Call Detection | Test Exclusion |
|---|---|---|---|---|---|
| Python | Yes | Yes (absolute + relative) | Yes (class inheritance) | Yes (regex + AST) | Yes |
| TypeScript | Yes | Yes (`import`/`require`) | Yes (`extends`/`implements`) | Yes (regex + AST) | Yes |
| Go | Yes | Yes (`go.mod`-aware) | Yes (interface satisfaction) | Yes (regex + AST) | Yes |
| Rust | Yes | Yes (`use`/`mod`) | Yes (`impl Trait for`) | — | Yes |
| Java | Yes | Yes (`import`) | Yes (`extends`/`implements`) | — | Yes |
| C/C++ | Yes | Yes (`#include`) | Yes (class inheritance) | — | Yes |
| C# | Yes | Yes (`using`) | Yes (class/interface inheritance) | — | Yes |
| PHP | Yes | Yes (`use`/`namespace`) | Yes (`extends`/`implements`) | — | Yes |
| Ruby | Yes | Yes (`require`/`require_relative`) | Yes (class inheritance, module `include`) | — | Yes |

---

## Language Recognizers

### Python (.py, .pyi)

- **Flask / FastAPI**: `@app.route()`, `@router.get()`, `@router.post()`, etc. → `endpoint` nodes
- **SQLAlchemy**: Classes inheriting from `Base` or `db.Model` with `__tablename__` → `database_table` nodes
- **Celery**: `@app.task`, `@shared_task`, `@celery.task` → `worker` nodes
- **Environment**: `os.environ["KEY"]`, `os.getenv("KEY")` → `env_var` nodes
- **HTTP clients**: `requests.get()`, `requests.post()`, etc. → `external_api` nodes
- **Class definitions** → `service` nodes

### TypeScript (.ts, .tsx, .mts, .cts)

- **Express / Fastify / Koa**: Route handler patterns → `endpoint` nodes
- **NestJS**: `@Get()`, `@Post()`, `@Controller()` decorators → `endpoint` nodes
- **TypeORM**: `@Entity()` decorators → `database_table` nodes
- **Prisma**: `prisma.model.find*`, `prisma.model.create`, etc. → `database_table` nodes
- **Environment**: `process.env.KEY` → `env_var` nodes
- **HTTP clients**: `fetch()`, `axios.*` calls → `external_api` nodes
- **Event emitters**: `emit()`, `on()` patterns → `event` nodes
- **React / Vue**: Component definitions → `frontend_component` nodes
- **Bull / BullMQ**: Queue patterns → `queue` / `worker` nodes

### Go (.go)

- **net/http**: `http.HandleFunc()`, `http.Handle()` → `endpoint` nodes
- **Gin / Echo / Chi**: Router method patterns → `endpoint` nodes
- **GORM**: Model struct patterns → `database_table` nodes
- **db.Table**: Direct table references → `database_table` nodes
- **Environment**: `os.Getenv()` → `env_var` nodes
- **HTTP clients**: `http.Get()`, `http.Post()` → `external_api` nodes

### Rust (.rs)

- **Actix / Rocket**: Route attribute macros (`#[get()]`, `#[post()]`) → `endpoint` nodes
- **Axum**: Router method patterns → `endpoint` nodes
- **Diesel**: `table!` macro, `#[derive(Queryable)]` → `database_table` nodes
- **Environment**: `env::var()`, `env!()` → `env_var` nodes
- **HTTP clients**: `reqwest::get()`, `reqwest::Client` → `external_api` nodes

### Java (.java)

- **Spring**: `@GetMapping`, `@PostMapping`, `@RequestMapping` → `endpoint` nodes
- **JPA**: `@Entity`, `@Table` annotations → `database_table` nodes
- **Environment**: `System.getenv()`, `@Value("${...}")` → `env_var` nodes
- **HTTP clients**: `RestTemplate`, `WebClient` → `external_api` nodes
- **Messaging**: `@RabbitListener`, `@KafkaListener` → `worker` nodes

### C/C++ (.c, .cpp, .h, .hpp)

- **Endpoints**: HTTP server handler patterns → `endpoint` nodes
- **Database**: SQL query patterns, database connection strings → `database_table` nodes
- **Environment**: `getenv()`, `std::getenv()` → `env_var` nodes
- **HTTP clients**: `curl_easy_*`, `httplib::Client` → `external_api` nodes

### C# (.cs)

- **ASP.NET**: `[HttpGet]`, `[HttpPost]`, `[Route]` attributes → `endpoint` nodes
- **Entity Framework**: `DbSet<>`, `[Table]` attributes → `database_table` nodes
- **Environment**: `Environment.GetEnvironmentVariable()`, `IConfiguration` → `env_var` nodes
- **HTTP clients**: `HttpClient`, `RestClient` → `external_api` nodes
- **Messaging**: `[ServiceBusListener]`, RabbitMQ patterns → `worker` nodes

### PHP (.php)

- **Laravel / Symfony**: Route definitions, controller annotations → `endpoint` nodes
- **Eloquent / Doctrine**: Model and entity patterns → `database_table` nodes
- **Environment**: `getenv()`, `$_ENV`, `env()` → `env_var` nodes
- **HTTP clients**: `Guzzle`, `curl_*`, `file_get_contents` → `external_api` nodes
- **Queues**: Laravel queue worker patterns → `worker` nodes

### Ruby (.rb)

- **Rails**: Route definitions, controller actions → `endpoint` nodes
- **ActiveRecord**: Model class patterns, `create_table` migrations → `database_table` nodes
- **Environment**: `ENV["KEY"]`, `ENV.fetch` → `env_var` nodes
- **HTTP clients**: `Net::HTTP`, `Faraday`, `HTTParty` → `external_api` nodes
- **Sidekiq / ActiveJob**: Worker and job class patterns → `worker` nodes

---

## Plugin System

The `RecognizerRegistry` maps file extensions to recognizer classes. The registry is pre-populated with all built-in recognizers, but custom recognizers can be added by implementing the `PatternRecognizer` protocol and registering them for the appropriate file extensions.

Cross-file edge inference connects endpoints to database tables when a file references model class names from other files, regardless of language.

---

## AST-Aware Scanning

For more accurate pattern detection, install tree-sitter support:

```bash
uv pip install -e ".[ast]"
```

Then use `scanner_mode="ast"` when initializing:

```
codegiraffe_init(project_path="/home/user/my-project", scanner_mode="ast")
```

AST scanning detects the same patterns as regex scanning but with higher accuracy — it understands actual syntax trees rather than pattern-matching raw text. This is particularly useful for complex nested patterns, avoiding false positives, and call-graph detection (v0.9.0). When tree-sitter is available, the scanner uses AST-based call detection in Go, Python, and TypeScript for more accurate `calls` edges.

---

## See Also

- [Architecture](architecture.md) — Node and edge types produced by the scanner

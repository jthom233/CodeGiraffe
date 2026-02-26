import pytest
from pathlib import Path
from codegiraffe.graph import Node, Edge, GraphData, ArchGraph
from codegiraffe.schema import NodeType, EdgeType


# ---------------------------------------------------------------------------
# Shared server-state reset fixture (US6 — fixture consolidation)
# ---------------------------------------------------------------------------

@pytest.fixture
def reset_server_state():
    """Reset server module globals before/after each test to avoid cross-test pollution.

    Defined here so all test modules can reference it via conftest discovery
    instead of duplicating it locally.
    """
    import codegiraffe.server as server_module
    from codegiraffe.storage import JSONStorage
    from codegiraffe.versioning import VersionStore
    from codegiraffe.federation import GraphFederation

    server_module._graph = None
    server_module._storage = JSONStorage()
    server_module._version_store = VersionStore()
    server_module._federation = GraphFederation()
    server_module._initialized_project_paths = set()
    yield
    server_module._graph = None
    server_module._storage = JSONStorage()
    server_module._version_store = VersionStore()
    server_module._federation = GraphFederation()
    server_module._initialized_project_paths = set()

@pytest.fixture
def sample_nodes():
    return [
        Node(id="endpoint:/api/users", type=NodeType.ENDPOINT, label="GET /api/users"),
        Node(id="endpoint:/api/payments", type=NodeType.ENDPOINT, label="POST /api/payments"),
        Node(id="table:users", type=NodeType.DATABASE_TABLE, label="users table"),
        Node(id="table:payments", type=NodeType.DATABASE_TABLE, label="payments table"),
        Node(id="worker:send_email", type=NodeType.WORKER, label="Email sender worker"),
        Node(id="env:DATABASE_URL", type=NodeType.ENV_VAR, label="DATABASE_URL"),
        Node(id="service:AuthService", type=NodeType.SERVICE, label="Auth Service"),
        Node(id="queue:notifications", type=NodeType.QUEUE, label="Notification queue"),
    ]

@pytest.fixture
def sample_edges():
    return [
        Edge(source="endpoint:/api/users", target="table:users", type=EdgeType.READS),
        Edge(source="endpoint:/api/payments", target="table:payments", type=EdgeType.WRITES),
        Edge(source="endpoint:/api/payments", target="worker:send_email", type=EdgeType.TRIGGERS),
        Edge(source="worker:send_email", target="queue:notifications", type=EdgeType.PUBLISHES),
        Edge(source="service:AuthService", target="env:DATABASE_URL", type=EdgeType.DEPENDS_ON),
        Edge(source="endpoint:/api/users", target="service:AuthService", type=EdgeType.CALLS),
    ]

@pytest.fixture
def sample_graph(sample_nodes, sample_edges):
    graph = ArchGraph()
    for node in sample_nodes:
        graph.add_node(node)
    for edge in sample_edges:
        graph.add_edge(edge)
    return graph

@pytest.fixture
def sample_graph_data(sample_graph):
    return sample_graph.to_data()

@pytest.fixture
def sample_project(tmp_path):
    """Create a sample Python project for scanner testing."""
    # Flask app
    app_file = tmp_path / "app.py"
    app_file.write_text('''
from flask import Flask
app = Flask(__name__)

@app.route("/api/users", methods=["GET"])
def get_users():
    users = User.query.all()
    return jsonify(users)

@app.route("/api/users/<int:id>", methods=["DELETE"])
def delete_user(id):
    pass
''')

    # SQLAlchemy models
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "__init__.py").write_text("")
    (models_dir / "user.py").write_text('''
from sqlalchemy import Column, Integer, String
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String)
    DATABASE_URL = os.getenv("DATABASE_URL")
''')

    # Celery tasks
    tasks_file = tmp_path / "tasks.py"
    tasks_file.write_text('''
from celery import shared_task
import requests

@shared_task
def send_email(to, subject, body):
    requests.post("https://api.sendgrid.com/v3/mail/send", json={"to": to})
''')

    return tmp_path

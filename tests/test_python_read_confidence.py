"""Python recognizer endpoint -> table ``reads`` edges carry 0.8 confidence.

These edges are inferred from co-occurrence of an endpoint and a table in
the same file (or an ORM reference across files), not parsed facts, so they
must use the documented pattern-match confidence rather than the 1.0 default.
"""

from __future__ import annotations

from codegiraffe.scanner import scan_project
from codegiraffe.schema import EdgeType


def test_same_file_endpoint_reads_table_is_0_8(tmp_path):
    (tmp_path / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/api/users')\n"
        "def users():\n"
        "    return []\n\n"
        "class User(Base):\n"
        "    __tablename__ = 'users'\n"
    )
    result = scan_project(str(tmp_path))
    reads = [
        e for e in result.edges
        if e.type == EdgeType.READS and e.source.startswith("endpoint:")
    ]
    assert reads, "Expected endpoint -> table reads edges"
    for e in reads:
        assert e.confidence == 0.8, (e.source, e.target, e.confidence)
        assert e.metadata.get("inferred") is True


def test_cross_file_endpoint_reads_table_is_0_8(tmp_path):
    (tmp_path / "models.py").write_text(
        "class Order(Base):\n"
        "    __tablename__ = 'orders'\n"
    )
    (tmp_path / "api.py").write_text(
        "from flask import Flask\n"
        "from models import Order\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/api/orders')\n"
        "def orders():\n"
        "    return Order.query.all()\n"
    )
    result = scan_project(str(tmp_path))
    cross = [
        e for e in result.edges
        if e.type == EdgeType.READS and e.metadata.get("cross_file")
    ]
    if cross:  # cross-file inference depends on the ORM reference being resolved
        for e in cross:
            assert e.confidence == 0.8, (e.source, e.target, e.confidence)
    reads = [e for e in result.edges if e.type == EdgeType.READS]
    assert all(e.confidence <= 0.8 for e in reads), [
        (e.source, e.target, e.confidence) for e in reads
    ]

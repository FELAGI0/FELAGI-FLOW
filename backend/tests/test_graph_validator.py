"""Тесты валидатора графа — чистые функции, без БД и HTTP."""

from app.engine.graph_validator import validate_graph
from app.engine.node_schemas import NODE_SCHEMAS
from app.shared.schemas.workflow import Edge, Graph, Node


def _node(node_id: str, node_type: str, **params: object) -> Node:
    return Node(id=node_id, type=node_type, params=dict(params), position={"x": 0.0, "y": 0.0})


def _edge(edge_id: str, source: str, target: str, source_handle: str | None = None) -> Edge:
    return Edge(id=edge_id, source=source, target=target, sourceHandle=source_handle)


def _graph(nodes: list[Node], edges: list[Edge]) -> Graph:
    return Graph(nodes=nodes, edges=edges)


def test_valid_linear_graph() -> None:
    graph = _graph(
        [
            _node("t", "trigger_manual"),
            _node("s", "transform_set", fields=[{"name": "x", "value": "1"}]),
            _node("d", "debug", level="info", message="hi"),
        ],
        [_edge("e1", "t", "s"), _edge("e2", "s", "d")],
    )
    assert validate_graph(graph, NODE_SCHEMAS) == []


def test_valid_if_branching_graph() -> None:
    graph = _graph(
        [
            _node("t", "trigger_manual"),
            _node("i", "logic_if", left="1", op="=", right="1"),
            _node("d1", "debug", message="yes"),
            _node("d2", "debug", message="no"),
        ],
        [
            _edge("e1", "t", "i"),
            _edge("e2", "i", "d1", source_handle="true"),
            _edge("e3", "i", "d2", source_handle="false"),
        ],
    )
    assert validate_graph(graph, NODE_SCHEMAS) == []


def test_no_trigger() -> None:
    graph = _graph(
        [_node("s", "transform_set", fields=[]), _node("d", "debug", message="x")],
        [_edge("e1", "s", "d")],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("trigger" in e for e in errors)


def test_two_triggers() -> None:
    graph = _graph(
        [_node("t1", "trigger_manual"), _node("t2", "trigger_manual")],
        [],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("exactly one trigger" in e for e in errors)


def test_cycle_detected() -> None:
    graph = _graph(
        [
            _node("t", "trigger_manual"),
            _node("a", "transform_set", fields=[]),
            _node("b", "debug", message="x"),
        ],
        [_edge("e1", "t", "a"), _edge("e2", "a", "b"), _edge("e3", "b", "a")],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("cycle" in e for e in errors)


def test_edge_to_missing_node() -> None:
    graph = _graph(
        [_node("t", "trigger_manual")],
        [_edge("e1", "t", "ghost")],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("does not exist" in e for e in errors)


def test_duplicate_node_id() -> None:
    graph = _graph(
        [_node("t", "trigger_manual"), _node("t", "debug", message="x")],
        [],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("duplicate" in e for e in errors)


def test_node_without_incoming_edge() -> None:
    graph = _graph(
        [_node("t", "trigger_manual"), _node("d", "debug", message="x")],
        [],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("no incoming edge" in e for e in errors)


def test_merge_rejected() -> None:
    graph = _graph(
        [
            _node("t", "trigger_manual"),
            _node("s", "transform_set", fields=[]),
            _node("d", "debug", message="x"),
        ],
        [_edge("e1", "t", "d"), _edge("e2", "s", "d")],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("merge not supported" in e for e in errors)


def test_if_missing_true_handle() -> None:
    graph = _graph(
        [
            _node("t", "trigger_manual"),
            _node("i", "logic_if", left="1", op="=", right="1"),
            _node("d", "debug", message="x"),
        ],
        [_edge("e1", "t", "i"), _edge("e2", "i", "d", source_handle="false")],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("missing 'true' branch" in e for e in errors)


def test_if_edge_without_handle() -> None:
    graph = _graph(
        [
            _node("t", "trigger_manual"),
            _node("i", "logic_if", left="1", op="=", right="1"),
            _node("d1", "debug", message="a"),
            _node("d2", "debug", message="b"),
        ],
        [
            _edge("e1", "t", "i"),
            _edge("e2", "i", "d1"),  # без sourceHandle
            _edge("e3", "i", "d2", source_handle="false"),
        ],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("must set sourceHandle" in e for e in errors)


def test_missing_required_parameter() -> None:
    graph = _graph(
        [
            _node("t", "trigger_manual"),
            _node("d", "debug"),  # нет обязательного message
        ],
        [_edge("e1", "t", "d")],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("invalid parameter" in e for e in errors)


def test_unknown_node_type() -> None:
    graph = _graph(
        [_node("t", "trigger_manual"), _node("x", "action_nonexistent")],
        [_edge("e1", "t", "x")],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("unknown type" in e for e in errors)


def test_invalid_enum_parameter() -> None:
    graph = _graph(
        [
            _node("t", "trigger_manual"),
            _node("i", "logic_if", left="1", op="nonsense", right="1"),
        ],
        [_edge("e1", "t", "i")],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("invalid parameter" in e for e in errors)


def test_trigger_with_incoming_edge_rejected() -> None:
    graph = _graph(
        [_node("t", "trigger_manual"), _node("s", "transform_set", fields=[])],
        [_edge("e1", "s", "t")],
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("must not have incoming edges" in e for e in errors)
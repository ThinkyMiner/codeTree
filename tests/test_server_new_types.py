"""Tests that the MCP server correctly formats new symbol types (trait, enum, type)."""
import pytest
from codetree.server import create_server


@pytest.fixture
def extended_repo(tmp_path):
    """Repo with Rust traits/enums, Java enums, and TS type aliases."""
    (tmp_path / "traits.rs").write_text("""\
pub trait Display {
    fn fmt(&self) -> String;
}

pub enum Color {
    Red,
    Green,
    Blue,
}

pub struct Canvas;

impl Canvas {
    pub fn new() -> Self { Canvas }
}
""")
    (tmp_path / "enums.java").write_text("""\
public enum Status {
    ACTIVE, INACTIVE;
    public String label() { return name(); }
}
""")
    (tmp_path / "types.ts").write_text("""\
type Props = { name: string };
export type Result<T> = { ok: boolean; value: T };
interface Shape { area(): number; }
class Circle implements Shape {
    area(): number { return 0; }
}
""")
    (tmp_path / "Worker.swift").write_text("""\
actor Worker {
    func run() {}
}
""")
    return tmp_path


def test_skeleton_shows_rust_traits_and_enums(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_file_skeleton@"].fn
    output = fn(file_path="traits.rs")
    assert "trait Display" in output
    assert "enum Color" in output
    assert "struct Canvas" in output


def test_skeleton_shows_java_enums(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_file_skeleton@"].fn
    output = fn(file_path="enums.java")
    assert "enum Status" in output
    assert "def label" in output


def test_skeleton_shows_ts_type_aliases(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_file_skeleton@"].fn
    output = fn(file_path="types.ts")
    assert "type Props" in output
    assert "type Result" in output
    assert "interface Shape" in output
    assert "class Circle" in output


def test_skeleton_shows_swift_actor(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_file_skeleton@"].fn
    assert fn(file_path="Worker.swift") == "actor Worker → line 1\n  def run() (in Worker) → line 2"
    assert fn(file_path="Worker.swift", format="compact") == "act Worker:1\n.run():2"


def test_get_symbol_rust_trait(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_symbol@"].fn
    output = fn(file_path="traits.rs", symbol_name="Display")
    assert "trait Display" in output
    assert "fn fmt" in output


def test_get_symbol_rust_enum(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_symbol@"].fn
    output = fn(file_path="traits.rs", symbol_name="Color")
    assert "enum Color" in output


def test_get_symbol_java_enum(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_symbol@"].fn
    output = fn(file_path="enums.java", symbol_name="Status")
    assert "enum Status" in output


def test_get_symbol_ts_type_alias(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_symbol@"].fn
    output = fn(file_path="types.ts", symbol_name="Props")
    assert "Props" in output


def test_get_symbol_ts_interface(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_symbol@"].fn
    output = fn(file_path="types.ts", symbol_name="Shape")
    assert "interface Shape" in output


def test_get_symbol_ts_method(extended_repo):
    mcp = create_server(str(extended_repo))
    fn = mcp.local_provider._components["tool:get_symbol@"].fn
    output = fn(file_path="types.ts", symbol_name="area")
    assert "area()" in output


def test_get_symbol_js_method(extended_repo, tmp_path):
    (tmp_path / "calc.js").write_text("""\
class Calculator {
    add(a, b) { return a + b; }
}
""")
    mcp = create_server(str(tmp_path))
    fn = mcp.local_provider._components["tool:get_symbol@"].fn
    output = fn(file_path="calc.js", symbol_name="add")
    assert "add(a, b)" in output


def test_get_symbol_go_method(extended_repo, tmp_path):
    (tmp_path / "server.go").write_text("""\
package main

type Server struct{ port int }

func (s *Server) Start() error { return nil }
""")
    mcp = create_server(str(tmp_path))
    fn = mcp.local_provider._components["tool:get_symbol@"].fn
    output = fn(file_path="server.go", symbol_name="Start")
    assert "func (s *Server) Start()" in output

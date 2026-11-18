"""
Exhaustive tests for the Swift plugin covering idiomatic code patterns.

Code style categories:
  - Types: class, struct, enum (cases, associated values), protocol, extension, actor, typealias
  - Members: init/deinit, subscript, computed properties, nested types, doc comments
  - Protocol + extension, generics with where, async/await/throws, property wrappers, SwiftUI
  - extract_symbol_source, calls, complexity, variables, imports, test detection
"""
from codetree.indexer import Indexer
from codetree.graph.builder import GraphBuilder
from codetree.graph.store import GraphStore
from codetree.languages.swift import SwiftPlugin

P = SwiftPlugin()


def _item(result, name, **fields):
    return next(x for x in result if x["name"] == name and all(x[k] == v for k, v in fields.items()))


# ─── Type declarations ───────────────────────────────────────────────────────

def test_declaration_kinds():
    src = b"""\
class A {}
struct B {}
enum C { case x }
protocol D {}
actor E {}
typealias F = (Int) -> Void
"""
    kinds = {x["name"]: x["type"] for x in P.extract_skeleton(src)}
    assert kinds == {"A": "class", "B": "struct", "C": "enum", "x": "case",
                     "D": "interface", "E": "class", "F": "type"}


def test_extension_named_after_extended_type():
    src = b"""\
protocol Shape { func area() -> Double }
struct Square { let side: Double }
extension Square: Shape {
    func area() -> Double { side * side }
}
"""
    result = P.extract_skeleton(src)
    ext = _item(result, "Square", line=3)
    assert ext["type"] == "class"
    assert ext["parent"] is None
    assert _item(result, "area", line=4)["parent"] == "Square"
    assert _item(result, "area", line=1)["parent"] == "Shape"


def test_extension_of_nested_type_uses_last_component():
    src = b"extension Outer.Inner {\n    func go() {}\n}\n"
    result = P.extract_skeleton(src)
    assert _item(result, "Inner")["type"] == "class"
    assert _item(result, "go")["parent"] == "Inner"


def test_generic_extension_with_where():
    src = b"extension Array where Element: Equatable {\n    func dedup() -> [Element] { [] }\n}\n"
    result = P.extract_skeleton(src)
    assert _item(result, "Array")["line"] == 1
    assert _item(result, "dedup")["parent"] == "Array"


def test_enum_cases_with_associated_values():
    src = b"""\
enum LoadState {
    case idle, loading
    case loaded(Data)
    case failed(error: Error, retries: Int)
}
"""
    result = P.extract_skeleton(src)
    cases = [(x["name"], x["params"]) for x in result if x["type"] == "case"]
    assert cases == [("idle", ""), ("loading", ""), ("loaded", "(Data)"),
                     ("failed", "(error: Error, retries: Int)")]
    assert all(x["parent"] == "LoadState" for x in result if x["type"] == "case")


def test_nested_types_have_parent():
    src = b"""\
struct Outer {
    enum Mode { case on }
    struct Config {
        class Store {
            func save() {}
        }
    }
}
"""
    result = P.extract_skeleton(src)
    assert _item(result, "Outer")["parent"] is None
    assert _item(result, "Mode")["parent"] == "Outer"
    assert _item(result, "Config")["parent"] == "Outer"
    assert _item(result, "Store")["parent"] == "Config"
    assert _item(result, "save")["parent"] == "Store"


# ─── Members ─────────────────────────────────────────────────────────────────

MEMBERS = b"""\
final class Cache {
    init(capacity: Int = 10) {}
    convenience init?(name: String) { self.init(capacity: 1) }
    deinit { flush() }
    subscript(key: String) -> Data? { storage[key] }
    var count: Int { storage.count }
    var isEmpty: Bool {
        get { count == 0 }
        set { reset() }
    }
    var stored = 0
    static func == (lhs: Cache, rhs: Cache) -> Bool { true }
}
"""


def test_init_deinit_subscript_computed_properties():
    result = P.extract_skeleton(MEMBERS)
    methods = [(x["name"], x["line"], x["params"]) for x in result if x["type"] == "method"]
    assert methods == [
        ("init", 2, "(capacity: Int = 10)"),
        ("init", 3, "(name: String)"),
        ("deinit", 4, ""),
        ("subscript", 5, "(key: String)"),
        ("count", 6, ""),
        ("isEmpty", 7, ""),
        ("==", 12, "(lhs: Cache, rhs: Cache)"),
    ]
    assert all(x["parent"] == "Cache" for x in result if x["type"] == "method")


def test_stored_property_not_in_skeleton():
    assert not any(x["name"] == "stored" for x in P.extract_skeleton(MEMBERS))


def test_every_skeleton_function_resolves():
    src = MEMBERS + b"protocol P { func req(x: Int) }\nfunc free() {}\n"
    for item in P.extract_skeleton(src):
        assert P.extract_symbol_source(src, item["name"]) is not None, item["name"]


def test_load_keeps_external_labels_and_closure_type():
    src = b"""\
class Loader {
    func load(from url: URL, completion: @escaping (Result<Data, Error>) -> Void) {}
}
"""
    load = _item(P.extract_skeleton(src), "load")
    assert load["params"] == "(from url: URL, completion: @escaping (Result<Data, Error>) -> Void)"


def test_generic_function_with_where():
    src = b"func swap<T>(_ a: inout T, _ b: inout T) where T: Equatable {}\n"
    fn = _item(P.extract_skeleton(src), "swap")
    assert fn["type"] == "function"
    assert fn["params"] == "(_ a: inout T, _ b: inout T)"


def test_async_throws_function():
    src = b"func fetch(id: Int) async throws -> User { try await api.user(id) }\n"
    assert _item(P.extract_skeleton(src), "fetch")["params"] == "(id: Int)"
    assert P.extract_calls_in_function(src, "fetch") == ["user"]


def test_doc_comments():
    src = b"""\
/// A user session.
/// Holds the token.
@MainActor
final class Session {
    /// Signs out.
    func signOut() {}

    func plain() {}

    // MARK: - Lifecycle
    /// Starts the session.
    func start() {}

    // MARK: - Helpers
    func helper() {}
}

/** Block doc. */
// MARK: - Store
actor Store {}
"""
    result = P.extract_skeleton(src)
    assert _item(result, "Session")["doc"] == "A user session."
    assert _item(result, "signOut")["doc"] == "Signs out."
    assert _item(result, "plain")["doc"] == ""
    assert _item(result, "start")["doc"] == "Starts the session."
    assert _item(result, "helper")["doc"] == ""
    assert _item(result, "Store")["doc"] == "Block doc."


# ─── Protocols, property wrappers, SwiftUI ───────────────────────────────────

def test_protocol_requirements():
    src = b"""\
protocol Repository {
    associatedtype Item
    var all: [Item] { get }
    init(path: String)
    func find(id: Int) -> Item?
}
"""
    result = P.extract_skeleton(src)
    assert _item(result, "Repository")["type"] == "interface"
    assert _item(result, "find")["params"] == "(id: Int)"
    assert _item(result, "find")["parent"] == "Repository"
    assert _item(result, "init")["parent"] == "Repository"


def test_published_view_model():
    src = b"""\
@MainActor
final class ProfileViewModel: ObservableObject {
    @Published private(set) var name = ""
    @Published var isLoading = false

    func refresh() async {
        isLoading = true
        name = await service.fetchName()
        isLoading = false
    }
}
"""
    result = P.extract_skeleton(src)
    assert [x["name"] for x in result] == ["ProfileViewModel", "refresh"]
    assert P.extract_calls_in_function(src, "refresh") == ["fetchName"]


SWIFTUI = b"""\
import SwiftUI

struct ContentView: View {
    @StateObject private var model = ProfileViewModel()

    var body: some View {
        VStack {
            Text(model.name)
                .font(.title)
            Button("Reload") { Task { await model.refresh() } }
        }
        .onAppear { model.start() }
    }
}
"""


def test_swiftui_body_is_method():
    body = _item(P.extract_skeleton(SWIFTUI), "body")
    assert body == {"type": "method", "name": "body", "line": 6, "parent": "ContentView",
                    "params": "", "doc": ""}


def test_swiftui_body_calls_include_trailing_closures():
    assert P.extract_calls_in_function(SWIFTUI, "body") == [
        "Button", "Task", "Text", "VStack", "font", "onAppear", "refresh", "start",
    ]


# ─── extract_symbol_source ───────────────────────────────────────────────────

def test_symbol_source_includes_attributes_and_modifiers():
    src = b"""\
class Store {
    @MainActor
    @available(iOS 15, *)
    private static func reload() {}
    @objc override func viewDidLoad() {}
}
"""
    source, line = P.extract_symbol_source(src, "reload")
    assert source.startswith("@MainActor\n    @available(iOS 15, *)\n    private static func reload()")
    assert line == 2
    source, _ = P.extract_symbol_source(src, "viewDidLoad")
    assert source.startswith("@objc override func viewDidLoad()")


def test_symbol_source_prefers_declaration_over_extension():
    src = b"extension Foo { func a() {} }\nstruct Foo { let x: Int }\n"
    source, line = P.extract_symbol_source(src, "Foo")
    assert source.startswith("struct Foo")
    assert line == 2


def test_symbol_source_falls_back_to_extension():
    src = b"extension String { func shout() -> String { uppercased() } }\n"
    source, line = P.extract_symbol_source(src, "String")
    assert source.startswith("extension String")
    assert line == 1


def test_symbol_source_computed_property():
    source, line = P.extract_symbol_source(SWIFTUI, "body")
    assert source.startswith("var body: some View {")
    assert line == 6


# ─── Calls ───────────────────────────────────────────────────────────────────

def test_call_forms():
    src = b"""\
class VM: Base {
    init() {
        super.init()
        let a = Foo<Int>()
        let b = Point(x: 1)
        self.configure()
        delegate?.didLoad()
        items.map { $0 }.filter { x in x.isValid }
        load(url) { result in handle(result) }
        let c: Bar = .init()
        #expect(a == b)
    }
}
"""
    assert P.extract_calls_in_function(src, "init") == [
        "Foo", "Point", "configure", "didLoad", "filter", "handle", "load", "map",
    ]


# ─── Complexity ──────────────────────────────────────────────────────────────

def test_complexity_all_branches():
    src = b"""\
func decide(a: Int?, b: Bool) throws -> Int {
    guard let v = a else { return 0 }
    if v > 1 && b || !b { } else if v == 2 { }
    let z = a ?? 0
    let t = b ? 1 : 2
    switch v {
    case 1: break
    case 2, 3: break
    default: break
    }
    for _ in 0..<3 { }
    while false { }
    repeat { } while false
    do { try run() } catch { }
    return z + t
}
"""
    result = P.compute_complexity(src, "decide")
    assert result["breakdown"] == {
        "guard": 1, "if": 2, "&&": 1, "||": 1, "??": 1, "ternary": 1,
        "case": 2, "for": 1, "while": 1, "repeat": 1, "catch": 1,
    }
    assert result["total"] == 14


def test_complexity_missing_function():
    assert P.compute_complexity(b"func a() {}\n", "b") is None


# ─── Variables ───────────────────────────────────────────────────────────────

def test_variables():
    src = b"""\
func process(_ items: [Item], limit: Int?) {
    let max: Int = limit ?? 10
    var (done, left) = (0, items.count)
    guard let first = items.first else { return }
    if let last = items.last { }
    while let next = queue.pop() { }
    for item in items { }
    items.forEach { entry in print(entry) }
    switch first { case .some(let wrapped): break; default: break }
    do { } catch let err { }
    let _ = 0
}
"""
    result = [(v["name"], v["type"], v["kind"]) for v in P.extract_variables(src, "process")]
    assert result == [
        ("items", "[Item]", "parameter"),
        ("limit", "Int?", "parameter"),
        ("max", "Int", "local"),
        ("done", "", "local"),
        ("left", "", "local"),
        ("first", "", "local"),
        ("last", "", "local"),
        ("next", "", "local"),
        ("item", "", "loop_var"),
        ("entry", "", "parameter"),
        ("wrapped", "", "local"),
        ("err", "", "local"),
    ]


# ─── Imports ─────────────────────────────────────────────────────────────────

def test_imports():
    src = b"import Foundation\n@testable import MyApp\nimport struct Swift.Array\n\nclass A {}\n"
    assert P.extract_imports(src) == [
        {"line": 1, "text": "import Foundation"},
        {"line": 2, "text": "@testable import MyApp"},
        {"line": 3, "text": "import struct Swift.Array"},
    ]


# ─── Test detection ──────────────────────────────────────────────────────────

TESTS = b"""\
import XCTest
import Testing
@testable import App

final class CalculatorTests: XCTestCase {
    override func setUp() {}
    func testAddition() { XCTAssertEqual(Calculator().add(1, 2), 3) }
    func testHelper(value: Int) {}
}

@Suite struct ParserTests {
    @Test("parses numbers") func parsesNumbers() { #expect(Parser().parse("1") == 1) }
    func helper() {}
}

@Test func standalone() {}
"""


def test_skeleton_flags_xctest_and_swift_testing():
    flagged = [x["name"] for x in P.extract_skeleton(TESTS) if x.get("is_test")]
    assert flagged == ["testAddition", "parsesNumbers", "standalone"]


def test_find_tests_finds_swift_tests(tmp_path):
    (tmp_path / "Calculator.swift").write_text(
        "struct Calculator {\n    func add(_ a: Int, _ b: Int) -> Int { a + b }\n}\n"
        "struct Parser {\n    func parse(_ s: String) -> Int { 0 }\n}\n"
    )
    (tmp_path / "CalculatorTests.swift").write_text(TESTS.decode())
    indexer = Indexer(str(tmp_path))
    indexer.build()
    names = {t["name"] for t in indexer.find_tests("Calculator.swift", "Calculator")}
    assert "testAddition" in names
    names = {t["name"] for t in indexer.find_tests("Calculator.swift", "Parser")}
    assert "parsesNumbers" in names


# ─── Graph build ─────────────────────────────────────────────────────────────

def test_graph_build_with_duplicate_names(tmp_path):
    (tmp_path / "Model.swift").write_text("""\
struct Foo {
    init() {}
    init(x: Int) { self.init() }
    func run() { helper() }
}
extension Foo {
    func helper() {}
}
""")
    indexer = Indexer(str(tmp_path))
    indexer.build()
    store = GraphStore(str(tmp_path))
    store.open()
    GraphBuilder(str(tmp_path), store).build(indexer)
    names = sorted(s.name for s in store.symbols_by_file("Model.swift"))
    store.close()
    assert names == ["Foo", "helper", "init", "run"]

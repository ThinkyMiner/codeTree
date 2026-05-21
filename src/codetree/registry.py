from pathlib import Path
from .languages.base import LanguagePlugin
from .languages.python import PythonPlugin
from .languages.javascript import JavaScriptPlugin
from .languages.typescript import TypeScriptPlugin, TSXPlugin
from .languages.go import GoPlugin
from .languages.rust import RustPlugin
from .languages.java import JavaPlugin
from .languages.c import CPlugin
from .languages.cpp import CppPlugin
from .languages.ruby import RubyPlugin
from .languages.kotlin import KotlinPlugin

# All supported file extensions mapped to plugin instances.
# To add a new language: import its plugin and add its extensions here.
PLUGINS: dict[str, LanguagePlugin] = {
    ".py":  PythonPlugin(),
    ".js":  JavaScriptPlugin(),
    ".jsx": JavaScriptPlugin(),
    ".ts":  TypeScriptPlugin(),
    ".tsx": TSXPlugin(),
    ".go":  GoPlugin(),
    ".rs":  RustPlugin(),
    ".java": JavaPlugin(),
    ".c":   CPlugin(),
    ".h":   CPlugin(),
    ".cpp":  CppPlugin(),
    ".cc":   CppPlugin(),
    ".cxx":  CppPlugin(),
    ".hpp":  CppPlugin(),
    ".hh":   CppPlugin(),
    ".rb":   RubyPlugin(),
    ".kt":   KotlinPlugin(),
}


def get_plugin(path: Path) -> LanguagePlugin | None:
    """Return the plugin for this file's extension, or None if unsupported."""
    return PLUGINS.get(path.suffix)

"""Language-specific pattern recognizers for Code Giraffe."""

from codegiraffe.recognizers.cpp import CppRecognizer
from codegiraffe.recognizers.csharp import CSharpRecognizer
from codegiraffe.recognizers.csproj import CsprojRecognizer
from codegiraffe.recognizers.go import GoRecognizer
from codegiraffe.recognizers.java import JavaRecognizer
from codegiraffe.recognizers.lua import LuaRecognizer
from codegiraffe.recognizers.packages_config import PackagesConfigRecognizer
from codegiraffe.recognizers.php import PhpRecognizer
from codegiraffe.recognizers.ruby import RubyRecognizer
from codegiraffe.recognizers.rust import RustRecognizer
from codegiraffe.recognizers.typescript import TypeScriptRecognizer

__all__ = [
    "CppRecognizer",
    "CSharpRecognizer",
    "CsprojRecognizer",
    "TypeScriptRecognizer",
    "GoRecognizer",
    "LuaRecognizer",
    "PackagesConfigRecognizer",
    "RustRecognizer",
    "JavaRecognizer",
    "PhpRecognizer",
    "RubyRecognizer",
]

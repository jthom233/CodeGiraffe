"""Language-specific pattern recognizers for Code Giraffe."""

from codegiraffe.recognizers.cpp import CppRecognizer
from codegiraffe.recognizers.csharp import CSharpRecognizer
from codegiraffe.recognizers.go import GoRecognizer
from codegiraffe.recognizers.java import JavaRecognizer
from codegiraffe.recognizers.php import PhpRecognizer
from codegiraffe.recognizers.ruby import RubyRecognizer
from codegiraffe.recognizers.rust import RustRecognizer
from codegiraffe.recognizers.typescript import TypeScriptRecognizer

__all__ = [
    "CppRecognizer",
    "CSharpRecognizer",
    "TypeScriptRecognizer",
    "GoRecognizer",
    "RustRecognizer",
    "JavaRecognizer",
    "PhpRecognizer",
    "RubyRecognizer",
]

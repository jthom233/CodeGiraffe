"""Tests for import parsing and inheritance/implementation detection in
C#, C/C++, PHP, and Ruby recognizers (v0.6.0).

Each test class exercises the recognizer's ability to:
- Parse project-internal imports (and exclude external/system ones)
- Detect class inheritance and interface implementation
"""

import pytest
from pathlib import Path

from codegiraffe.recognizers.csharp import CSharpRecognizer
from codegiraffe.recognizers.cpp import CppRecognizer
from codegiraffe.recognizers.php import PhpRecognizer
from codegiraffe.recognizers.ruby import RubyRecognizer
from codegiraffe.scanner import ImportInfo, ImplementationInfo


# ---------------------------------------------------------------------------
# C# Recognizer — imports and inheritance
# ---------------------------------------------------------------------------


class TestCSharpRecognizerImports:
    """Test CSharpRecognizer import and inheritance detection."""

    @pytest.fixture
    def recognizer(self, tmp_path):
        """Create a CSharpRecognizer with a fake project namespace."""
        rec = CSharpRecognizer()
        # Create a .cs file that declares a project namespace so the
        # recognizer learns "MyApp" as a project namespace root.
        project_file = tmp_path / "Models" / "User.cs"
        project_file.parent.mkdir(parents=True, exist_ok=True)
        project_file.write_text(
            "namespace MyApp.Models;\npublic class User {}\n",
            encoding="utf-8",
        )
        rec.set_project_root(str(tmp_path))
        return rec

    def test_using_project_namespace_returns_import(self, recognizer, tmp_path):
        """using MyApp.Services.Auth -> ImportInfo (matches project ns)."""
        code = """\
using MyApp.Services.Auth;

namespace MyApp.Controllers;

public class AuthController {
    private readonly Auth _auth;
}
"""
        file_path = tmp_path / "Controllers" / "AuthController.cs"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("Controllers/AuthController.cs"), code)

        assert len(result.imports) >= 1
        imp = result.imports[0]
        assert isinstance(imp, ImportInfo)
        assert imp.module_path == "MyApp.Services.Auth"
        assert imp.style == "absolute"
        assert "Auth" in imp.symbols

    def test_using_system_namespace_excluded(self, recognizer, tmp_path):
        """using System.Collections.Generic -> NOT returned (system ns)."""
        code = """\
using System.Collections.Generic;
using Microsoft.Extensions.Logging;

namespace MyApp.Services;

public class DataService {
    private readonly List<string> _items = new();
}
"""
        file_path = tmp_path / "Services" / "DataService.cs"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("Services/DataService.cs"), code)

        # Neither System nor Microsoft namespaces should appear
        for imp in result.imports:
            assert not imp.module_path.startswith("System")
            assert not imp.module_path.startswith("Microsoft")

    def test_class_inherits_base_class(self, recognizer, tmp_path):
        """class OrderService : BaseService -> ImplementationInfo."""
        code = """\
namespace MyApp.Services;

public class OrderService : BaseService
{
    public void Process() { }
}
"""
        file_path = tmp_path / "Services" / "OrderService.cs"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("Services/OrderService.cs"), code)

        assert len(result.implementations) >= 1
        impl = result.implementations[0]
        assert isinstance(impl, ImplementationInfo)
        assert impl.child_class == "OrderService"
        assert impl.parent_class == "BaseService"

    def test_class_implements_interface(self, recognizer, tmp_path):
        """class PaymentService : IPaymentGateway -> ImplementationInfo."""
        code = """\
namespace MyApp.Services;

public class PaymentService : IPaymentGateway
{
    public void Charge(decimal amount) { }
}
"""
        file_path = tmp_path / "Services" / "PaymentService.cs"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("Services/PaymentService.cs"), code)

        assert len(result.implementations) >= 1
        impl = result.implementations[0]
        assert isinstance(impl, ImplementationInfo)
        assert impl.child_class == "PaymentService"
        assert impl.parent_class == "IPaymentGateway"


# ---------------------------------------------------------------------------
# C/C++ Recognizer — imports and inheritance
# ---------------------------------------------------------------------------


class TestCppRecognizerImports:
    """Test CppRecognizer import and inheritance detection."""

    @pytest.fixture
    def recognizer(self):
        return CppRecognizer()

    def test_quoted_include_returns_import(self, recognizer, tmp_path):
        """#include "utils/logger.h" -> ImportInfo (local/quoted)."""
        code = """\
#include "utils/logger.h"
#include "core/engine.h"

class App {
public:
    void run();
};
"""
        file_path = tmp_path / "app.cpp"
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("app.cpp"), code)

        assert len(result.imports) >= 2
        module_paths = [imp.module_path for imp in result.imports]
        # Path separators converted to dots, extension stripped
        assert "utils.logger" in module_paths
        assert "core.engine" in module_paths
        for imp in result.imports:
            assert isinstance(imp, ImportInfo)
            assert imp.style == "absolute"

    def test_angle_bracket_include_excluded(self, recognizer, tmp_path):
        """#include <iostream> -> NOT returned (system header)."""
        code = """\
#include <iostream>
#include <vector>
#include <cstdlib>

int main() {
    std::cout << "hello";
    return 0;
}
"""
        file_path = tmp_path / "main.cpp"
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("main.cpp"), code)

        # System angle-bracket includes should not appear in imports
        assert len(result.imports) == 0

    def test_class_inherits_base(self, recognizer, tmp_path):
        """class Derived : public Base -> ImplementationInfo."""
        code = """\
#include "base.h"

class Derived : public Base {
public:
    void doSomething() override;
};
"""
        file_path = tmp_path / "derived.h"
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("derived.h"), code)

        assert len(result.implementations) >= 1
        impl = result.implementations[0]
        assert isinstance(impl, ImplementationInfo)
        assert impl.child_class == "Derived"
        assert impl.parent_class == "Base"


# ---------------------------------------------------------------------------
# PHP Recognizer — imports and inheritance
# ---------------------------------------------------------------------------


class TestPHPRecognizerImports:
    """Test PhpRecognizer import and inheritance detection."""

    @pytest.fixture
    def recognizer(self, tmp_path):
        """Create a PhpRecognizer with a fake project namespace."""
        rec = PhpRecognizer()
        # Create a PHP file declaring "App" as the project root namespace
        model_file = tmp_path / "Models" / "User.php"
        model_file.parent.mkdir(parents=True, exist_ok=True)
        model_file.write_text(
            "<?php\nnamespace App\\Models;\nclass User {}\n",
            encoding="utf-8",
        )
        rec.set_project_root(str(tmp_path))
        return rec

    def test_use_statement_returns_import(self, recognizer, tmp_path):
        """use App\\Models\\User -> ImportInfo with dots in module_path."""
        code = """\
<?php

namespace App\\Controllers;

use App\\Models\\User;

class UserController {
    public function index() {
        return User::all();
    }
}
"""
        file_path = tmp_path / "Controllers" / "UserController.php"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("Controllers/UserController.php"), code)

        assert len(result.imports) >= 1
        imp = result.imports[0]
        assert isinstance(imp, ImportInfo)
        # Backslashes should be converted to dots
        assert imp.module_path == "App.Models.User"
        assert imp.style == "absolute"
        assert "User" in imp.symbols

    def test_class_extends_parent(self, recognizer, tmp_path):
        """class AdminController extends Controller -> ImplementationInfo."""
        code = """\
<?php

namespace App\\Controllers;

class AdminController extends Controller {
    public function dashboard() {
        return view('admin.dashboard');
    }
}
"""
        file_path = tmp_path / "Controllers" / "AdminController.php"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("Controllers/AdminController.php"), code)

        assert len(result.implementations) >= 1
        impl = result.implementations[0]
        assert isinstance(impl, ImplementationInfo)
        assert impl.child_class == "AdminController"
        assert impl.parent_class == "Controller"

    def test_class_implements_interface(self, recognizer, tmp_path):
        """class PaymentService implements PaymentGateway -> ImplementationInfo."""
        code = """\
<?php

namespace App\\Services;

class PaymentService implements PaymentGateway {
    public function charge(float $amount): bool {
        return true;
    }
}
"""
        file_path = tmp_path / "Services" / "PaymentService.php"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("Services/PaymentService.php"), code)

        impl_names = [(i.child_class, i.parent_class) for i in result.implementations]
        assert ("PaymentService", "PaymentGateway") in impl_names


# ---------------------------------------------------------------------------
# Ruby Recognizer — imports and inheritance
# ---------------------------------------------------------------------------


class TestRubyRecognizerImports:
    """Test RubyRecognizer import and inheritance detection."""

    @pytest.fixture
    def recognizer(self):
        return RubyRecognizer()

    def test_require_relative_returns_import(self, recognizer, tmp_path):
        """require_relative 'models/user' -> ImportInfo with style='relative'."""
        code = """\
require_relative 'models/user'
require_relative 'services/auth_service'

class UsersController
  def index
    @users = User.all
  end
end
"""
        file_path = tmp_path / "controllers" / "users_controller.rb"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("controllers/users_controller.rb"), code)

        assert len(result.imports) >= 2
        module_paths = [imp.module_path for imp in result.imports]
        # Path separators converted to dots
        assert "models.user" in module_paths
        assert "services.auth_service" in module_paths
        for imp in result.imports:
            assert isinstance(imp, ImportInfo)
            assert imp.style == "relative"

    def test_class_inherits_custom_base(self, recognizer, tmp_path):
        """class Admin < User -> ImplementationInfo (non-framework base)."""
        code = """\
class Admin < User
  def admin?
    true
  end
end
"""
        file_path = tmp_path / "models" / "admin.rb"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("models/admin.rb"), code)

        assert len(result.implementations) >= 1
        impl = result.implementations[0]
        assert isinstance(impl, ImplementationInfo)
        assert impl.child_class == "Admin"
        assert impl.parent_class == "User"

    def test_require_external_gem_excluded(self, recognizer, tmp_path):
        """require 'json' (external gem) -> NOT returned as internal import."""
        code = """\
require 'json'
require 'net/http'
require 'yaml'

class ApiClient
  def fetch(url)
    uri = URI(url)
    Net::HTTP.get(uri)
  end
end
"""
        file_path = tmp_path / "lib" / "api_client.rb"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("lib/api_client.rb"), code)

        # Regular `require` (not require_relative) should NOT produce imports
        assert len(result.imports) == 0

    def test_framework_base_class_excluded(self, recognizer, tmp_path):
        """class User < ApplicationRecord -> NOT in implementations (framework base)."""
        code = """\
class User < ApplicationRecord
  has_many :posts
  validates :name, presence: true
end
"""
        file_path = tmp_path / "models" / "user.rb"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")

        result = recognizer.recognize(Path("models/user.rb"), code)

        # ApplicationRecord is in _RB_EXTERNAL_BASES, so no implementations
        assert len(result.implementations) == 0

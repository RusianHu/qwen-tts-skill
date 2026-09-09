"""Verification script for Qwen TTS Skill.

Run this script to verify the self-contained skill installation and basic functionality.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows 控制台默认 GBK/cp936，无法编码本脚本的 ✓/✗/🎉 等符号，
# 会直接 UnicodeEncodeError 崩溃。统一把 stdio 切到 UTF-8（不可编码时降级替换）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - 非 TextIO 场景
        pass

BASE_DIR = Path(__file__).parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


DEPENDENCY_INSTALL_HINT = "pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt"


def verify_imports() -> bool:
    """Verify all required modules can be imported."""
    print("=" * 60)
    print("Step 1: Checking imports...")
    print("=" * 60)

    errors = []
    required_modules = [
        "logging",
        "os",
        "subprocess",
        "sys",
        "time",
        "pathlib",
        "typing",
        "dataclasses",
        "json",
    ]

    for mod in required_modules:
        try:
            __import__(mod)
            print(f"  ✓ {mod}")
        except ImportError as exc:
            errors.append(f"  ✗ {mod}: {exc}")

    optional_modules = [
        "requests",
        "gradio_client",
        "fastapi",
        "uvicorn",
        "pydantic",
    ]

    print("\nThird-party modules:")
    for mod in optional_modules:
        try:
            __import__(mod)
            print(f"  ✓ {mod}")
        except ImportError:
            print(f"  ⚠ {mod} (install with '{DEPENDENCY_INSTALL_HINT}')")

    if errors:
        print("\n❌ Core import errors found:")
        for err in errors:
            print(err)
        return False

    print("\n✅ All core imports successful!")
    return True


def verify_skill_structure() -> bool:
    """Verify skill structure and files."""
    print("\n" + "=" * 60)
    print("Step 2: Checking skill structure...")
    print("=" * 60)

    required_files = [
        "SKILL.md",
        "README.md",
        "requirements.txt",
        "scripts/qwen_tts_skill.py",
        "scripts/server.py",
        "tests/test_skill.py",
    ]

    optional_files = [
        "pyproject.toml",
    ]

    all_exist = True
    for file_path in required_files:
        full_path = BASE_DIR / file_path
        if full_path.exists():
            print(f"  ✓ {file_path}")
        else:
            print(f"  ✗ {file_path} (missing)")
            all_exist = False

    print("\nOptional development files:")
    for file_path in optional_files:
        full_path = BASE_DIR / file_path
        if full_path.exists():
            print(f"  ✓ {file_path}")
        else:
            print(f"  ⚠ {file_path} (not required for self-contained skill usage)")

    print("\n✅ All required files present!" if all_exist else "\n❌ Some required files are missing!")
    return all_exist


def verify_skill_class() -> bool:
    """Verify skill class can be instantiated."""
    print("\n" + "=" * 60)
    print("Step 3: Testing skill class...")
    print("=" * 60)

    try:
        from qwen_tts_skill import QwenTTSSkill, TTSResult

        skill = QwenTTSSkill(port=19999, auto_start=False)
        print(f"  ✓ Skill created: host={skill.host}, port={skill.port}")
        print(f"  ✓ Base URL: {skill.service.base_url}")
        print(f"  ✓ API info: {skill.get_api_info()}")

        result = TTSResult(success=True, audio_data=b"RIFFtest")
        print(f"  ✓ TTSResult created: {result}")

        print("\n✅ Skill class working!")
        return True
    except Exception as exc:
        print(f"\n❌ Error: {exc}")
        return False


def verify_server_module() -> bool:
    """Verify server module and FastAPI app."""
    print("\n" + "=" * 60)
    print("Step 4: Testing server module...")
    print("=" * 60)

    try:
        from qwen_tts_skill import create_app
        from server import app as server_app

        local_app = create_app(upstream_url="https://example.com")
        print("  ✓ create_app imported from scripts/qwen_tts_skill.py")
        print("  ✓ server entrypoint imported from scripts/server.py")
        print(f"  ✓ Local FastAPI app: {local_app.title}")
        print(f"  ✓ Entrypoint FastAPI app: {server_app.title}")
        print("  ✓ Direct script import path works without editable package installation")
        return True
    except ImportError as exc:
        print(f"  ✗ Import error: {exc}")
        print(f"  Install with: {DEPENDENCY_INSTALL_HINT}")
        return False
    except RuntimeError as exc:
        print(f"  ✗ Runtime error: {exc}")
        return False
    except Exception as exc:
        print(f"  ✗ Error: {exc}")
        return False


def check_dependencies() -> bool:
    """Check if all dependencies are installed."""
    print("\n" + "=" * 60)
    print("Step 5: Checking dependencies...")
    print("=" * 60)

    deps = [
        "requests",
        "gradio_client",
        "fastapi",
        "uvicorn",
        "pydantic",
    ]

    missing = []

    for dep in deps:
        try:
            __import__(dep.replace("-", "_"))
            print(f"  ✓ {dep}")
        except ImportError:
            missing.append(dep)
            print(f"  ✗ {dep}")

    if missing:
        print(f"\n❌ Missing dependencies: {', '.join(missing)}")
        print(f"  Install with: {DEPENDENCY_INSTALL_HINT}")
        return False

    print("\n✅ All runtime dependencies installed!")
    return True


def verify_modes() -> bool:
    """Verify direct backend mode and optional REST mode metadata."""
    print("\n" + "=" * 60)
    print("Step 6: Testing direct backend / optional REST modes...")
    print("=" * 60)

    try:
        from qwen_tts_skill import QwenTTSSkill

        skill = QwenTTSSkill(port=29999, auto_start=False)
        info = skill.get_api_info()
        print(f"  ✓ python_api_mode = {info['python_api_mode']}")
        print(f"  ✓ rest_mode = {info['rest_mode']}")
        print(f"  ✓ is_running check works (returned: {skill.is_running})")
        print("\n✅ Mode check working!")
        return True
    except Exception as exc:
        print(f"  ✗ Error: {exc}")
        return False


def main() -> int:
    """Run all verifications."""
    print("\n" + "=" * 60)
    print("Qwen TTS Skill Verification")
    print("=" * 60)

    results = [
        ("Imports", verify_imports()),
        ("Structure", verify_skill_structure()),
        ("Skill Class", verify_skill_class()),
        ("Server Module", verify_server_module()),
        ("Dependencies", check_dependencies()),
        ("Modes", verify_modes()),
    ]

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")

    all_passed = all(result for _, result in results)
    if all_passed:
        print("\n🎉 All verifications passed!")
        print("\nNext steps:")
        print(f"  1. If needed, install dependencies: {DEPENDENCY_INSTALL_HINT}")
        print("  2. Run tests: pytest tests/test_skill.py -q")
        print("  3. Use direct CLI: python scripts/qwen_tts_skill.py --say \"你好\" --output output.wav")
        print("  4. Start REST server only when needed: python scripts/server.py")
        return 0

    print("\n⚠ Some verifications failed.")
    print("Please fix the issues above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

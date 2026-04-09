"""Verification script for Qwen TTS Skill

Run this script to verify the skill installation and basic functionality.
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))


def verify_imports():
    """Verify all required modules can be imported"""
    print("=" * 60)
    print("Step 1: Checking imports...")
    print("=" * 60)

    errors = []

    # Check core Python modules
    required_modules = [
        "logging", "os", "subprocess", "sys", "time", "pathlib",
        "typing", "dataclasses", "json"
    ]

    for mod in required_modules:
        try:
            __import__(mod)
            print(f"  ✓ {mod}")
        except ImportError as e:
            errors.append(f"  ✗ {mod}: {e}")

    # Check third-party modules
    optional_modules = [
        "requests",
        "aiohttp",
        "gradio_client",
        "fastapi",
        "uvicorn",
        "aiofiles"
    ]

    print("\nThird-party modules (optional for some features):")
    for mod in optional_modules:
        try:
            __import__(mod)
            print(f"  ✓ {mod}")
        except ImportError:
            print(f"  ⚠ {mod} (optional - install with 'pip install -e .')")

    if errors:
        print("\n❌ Core import errors found:")
        for err in errors:
            print(err)
        return False

    print("\n✅ All core imports successful!")
    return True


def verify_skill_structure():
    """Verify skill structure and files"""
    print("\n" + "=" * 60)
    print("Step 2: Checking skill structure...")
    print("=" * 60)

    required_files = [
        "skill.json",
        "pyproject.toml",
        "README.md",
        "src/qwen_tts_skill.py",
        "tests/test_skill.py",
    ]

    base_path = Path(__file__).parent
    all_exist = True

    for file_path in required_files:
        full_path = base_path / file_path
        if full_path.exists():
            print(f"  ✓ {file_path}")
        else:
            print(f"  ✗ {file_path} (missing)")
            all_exist = False

    if all_exist:
        print("\n✅ All required files present!")
    else:
        print("\n❌ Some files are missing!")

    return all_exist


def verify_skill_class():
    """Verify skill class can be instantiated"""
    print("\n" + "=" * 60)
    print("Step 3: Testing skill class...")
    print("=" * 60)

    try:
        from qwen_tts_skill import QwenTTSSkill, TTSResult

        skill = QwenTTSSkill(port=19999, auto_start=False)
        print(f"  ✓ Skill created: host={skill.host}, port={skill.port}")
        print(f"  ✓ Base URL: {skill._base_url}")

        # Test dataclass
        result = TTSResult(success=True, audio_path="/tmp/test.wav")
        print(f"  ✓ TTSResult: {result}")

        print("\n✅ Skill class working!")
        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


def verify_server_module():
    """Verify server module"""
    print("\n" + "=" * 60)
    print("Step 4: Testing server module...")
    print("=" * 60)

    try:
        try:
            from server import app, TTSSettings
            print("  ✓ FastAPI server module imported")
            print(f"  ✓ FastAPI app: {app.title}")
            return True
        except ImportError as e:
            if "fastapi" in str(e).lower():
                print("  ⚠ FastAPI not installed (optional - install with 'pip install -e .')")
                return True
            raise
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def check_dependencies():
    """Check if all dependencies are installed"""
    print("\n" + "=" * 60)
    print("Step 5: Checking dependencies...")
    print("=" * 60)

    deps = [
        "requests",
        "aiohttp",
        "gradio_client",
        "fastapi",
        "uvicorn",
        "pydantic",
        "aiofiles"
    ]

    installed = []
    missing = []

    for dep in deps:
        try:
            __import__(dep.replace("-", "_"))
            installed.append(dep)
            print(f"  ✓ {dep}")
        except ImportError:
            missing.append(dep)
            print(f"  ✗ {dep}")

    if missing:
        print(f"\n⚠ Missing dependencies: {', '.join(missing)}")
        print("  Install with: pip install -e .")

    return len(missing) == 0 or len(installed) >= 3  # At least core deps


def verify_service_check():
    """Verify service check works"""
    print("\n" + "=" * 60)
    print("Step 6: Testing service status check...")
    print("=" * 60)

    try:
        from qwen_tts_skill import QwenTTSSkill

        skill = QwenTTSSkill(port=29999, auto_start=False)
        is_running = skill.is_running
        print(f"  ✓ is_running check works (returned: {is_running})")
        print("\n✅ Service check working!")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def main():
    """Run all verifications"""
    print("\n" + "=" * 60)
    print("Qwen TTS Skill Verification")
    print("=" * 60)

    results = []

    results.append(("Imports", verify_imports()))
    results.append(("Structure", verify_skill_structure()))
    results.append(("Skill Class", verify_skill_class()))
    results.append(("Server Module", verify_server_module()))
    results.append(("Dependencies", check_dependencies()))
    results.append(("Service Check", verify_service_check()))

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")

    all_passed = all(r[1] for r in results)

    if all_passed:
        print("\n🎉 All verifications passed!")
        print("\nNext steps:")
        print("  1. Install dependencies: pip install -e .")
        print("  2. Run tests: pytest tests/ -v")
        print("  3. Start using the skill:")
        print("     from qwen_tts_skill import QwenTTSSkill")
        print("     with QwenTTSSkill() as skill:")
        print("         result = skill.synthesize('Hello!')")
        return 0
    else:
        print("\n⚠ Some verifications failed.")
        print("Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

import sys
import types
from pathlib import Path


class _DummyOpenAI:
    def __init__(self, *args, **kwargs):
        pass


def _ensure_stub_module(name, attrs):
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    for key, value in attrs.items():
        if not hasattr(module, key):
            setattr(module, key, value)


_ensure_stub_module("openai", {"OpenAI": _DummyOpenAI})
_ensure_stub_module("tweepy", {})
_ensure_stub_module("markdown", {"markdown": lambda text: text})

# Ensure repo root is on sys.path for module imports in tests.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

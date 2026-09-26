from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_module_path = Path(__file__).with_name("api_systemInfo.py")
_spec = spec_from_file_location("api_systemInfo", _module_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load api_systemInfo from {_module_path}")

_api_systemInfo = module_from_spec(_spec)
_spec.loader.exec_module(_api_systemInfo)

_public_names = getattr(_api_systemInfo, "__all__", [name for name in dir(_api_systemInfo) if not name.startswith("_")])
for _name in _public_names:
    globals()[_name] = getattr(_api_systemInfo, _name)

__doc__ = _api_systemInfo.__doc__
__all__ = _public_names

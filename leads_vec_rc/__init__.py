from importlib.util import find_spec as _find_spec

if not _find_spec("fastapi"):
    raise ImportError("Please install `fastapi` to run this module\n>>>pip install \"fastapi[all]\"")

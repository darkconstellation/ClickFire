from __future__ import annotations

import importlib.util


modules = ["PIL", "cv2", "cryptography", "moviepy", "imageio", "numpy", "av"]
print({name: bool(importlib.util.find_spec(name)) for name in modules})
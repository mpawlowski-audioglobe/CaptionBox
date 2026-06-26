import os
import site
from pathlib import Path


def prepare_cuda_paths():
    """Add NVIDIA DLL folders installed by pip to Windows DLL search path."""
    if os.name != "nt":
        return []

    added = []
    roots = []

    try:
        for base in site.getsitepackages():
            nvidia_dir = Path(base) / "nvidia"
            if nvidia_dir.exists():
                roots.append(nvidia_dir)
    except Exception:
        pass

    try:
        user_dir = Path(site.getusersitepackages()) / "nvidia"
        if user_dir.exists():
            roots.append(user_dir)
    except Exception:
        pass

    for root in roots:
        for dll_file in root.rglob("*.dll"):
            folder = str(dll_file.parent)
            if folder in added:
                continue
            added.append(folder)
            try:
                os.add_dll_directory(folder)
            except Exception:
                pass

    if added:
        os.environ["PATH"] = ";".join(added) + ";" + os.environ.get("PATH", "")

    return added

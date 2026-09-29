"""Environment audit (directive STEP 1). Read-only; never prints secrets."""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGES = ["numpy", "pandas", "scipy", "sklearn", "yaml", "requests", "fastapi", "uvicorn", "duckdb", "pyarrow",
            "pytest", "hypothesis", "polars", "torch", "xgboost", "lightgbm"]


def _mem_gb() -> float | None:
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
    except (ValueError, OSError):
        pass
    try:  # Windows
        import ctypes

        class MEMSTAT(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MEMSTAT()
        st.dwLength = ctypes.sizeof(MEMSTAT)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
        return round(st.ullTotalPhys / 1e9, 1)
    except Exception:
        return None


def _gpu() -> str:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return "none detected (CPU-only; GPU is optional)"
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True,
                             text=True, timeout=10, check=False)
        return out.stdout.strip() or "nvidia-smi present, no GPU reported"
    except (OSError, subprocess.SubprocessError):
        return "nvidia-smi present but failed"


def environment_audit(root: Path) -> dict:
    pkgs = {}
    for p in PACKAGES:
        try:
            m = importlib.import_module(p)
            pkgs[p] = getattr(m, "__version__", "?")
        except Exception:
            pkgs[p] = None
    du = shutil.disk_usage(root)
    git = {}
    try:
        br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=root, timeout=10, check=False)
        st = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=root, timeout=10, check=False)
        git = {"branch": br.stdout.strip(), "dirty_files": len([l for l in st.stdout.splitlines() if l.strip()])}
    except (OSError, subprocess.SubprocessError):
        git = {"available": False}
    return {
        "os": f"{platform.system()} {platform.release()}", "platform": platform.platform(),
        "python": sys.version.split()[0], "executable": sys.executable,
        "cpu_count": os.cpu_count(), "cpu": platform.processor() or platform.machine(),
        "ram_gb": _mem_gb(), "gpu": _gpu(),
        "disk_free_gb": round(du.free / 1e9, 1), "disk_total_gb": round(du.total / 1e9, 1),
        "packages": pkgs, "git": git, "project_root": str(root),
        "data_dir_exists": (root / "data").exists(), "config_exists": (root / "config.yaml").exists(),
        "env_file_present": (root / ".env").exists(),
    }

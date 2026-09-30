from __future__ import annotations

import argparse
import contextlib
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional


APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WANDER_HOME") or (APP_ROOT / "data"))
MODELS_DIR = Path(os.environ.get("WANDER_MODELS") or (APP_ROOT / "models"))
CONFIG_PATH = DATA_DIR / "config.toml"
SESSIONS_DIR = DATA_DIR / "sessions"
HISTORY_FILE = DATA_DIR / "history"
LAST_MODEL_FILE = DATA_DIR / "last_model.json"
AUTOSAVE_NAME = "autosave"
LOG_PATH = DATA_DIR / "wander.log"
MODELS_CACHE = DATA_DIR / "models-cache.json"
PERSONA_FILE = APP_ROOT / "personalization.txt"
MEMORY_FILE = DATA_DIR / "memory.txt"

PERSONA_TEMPLATE = (
    "# ============================================================\n"
    "#  WANDER — PERSONALIZATION\n"
    "#\n"
    "#  Lines starting with # are ignored — they are tips, not\n"
    "#  instructions. Write anything below and it becomes part of\n"
    "#  Wander's mind. Changes apply INSTANTLY, even mid-chat.\n"
    "# ============================================================\n"
    "#\n"
    "# --- ABOUT YOU (who Wander is talking to) ---\n"
    "# My name is ...\n"
    "# I work as / I study ...\n"
    "# I prefer short answers / detailed step-by-step answers\n"
    "# Always answer me in <language>\n"
    "#\n"
    "# --- WANDER'S PERSONALITY (who Wander should be) ---\n"
    "# Your name is ...\n"
    "# You are warm and witty / formal and precise / strict like a coach\n"
    "# Use light humor / emojis / no emojis\n"
    "# When I ask about code, prefer <language>\n"
)


try:
    import rich.box as rbox
    from rich.align import Align
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.markup import escape as resc
    from rich.panel import Panel
    from rich.progress_bar import ProgressBar
    from rich.table import Table
    from rich.text import Text
except ImportError:
    sys.stderr.write("Wander needs 'rich'. Run:  pip install rich prompt_toolkit\n")
    raise SystemExit(1)




SUPPORTED_ARCHS = {
    "llama", "mistral", "qwen2", "qwen2moe", "phi3", "gemma", "gemma2",
    "gpt2", "falcon", "bloom", "stablelm", "starcoder2", "mamba",
    "nemotron", "granite", "cohere",
}
ARCH_FRIENDLY = {
    "llama": "Llama / Mistral family", "mistral": "Mistral",
    "qwen2": "Qwen2", "qwen2moe": "Qwen2-MoE", "phi3": "Phi-3",
    "gemma": "Gemma", "gemma2": "Gemma2", "gpt2": "GPT-2",
    "falcon": "Falcon", "bloom": "BLOOM", "stablelm": "StableLM",
    "starcoder2": "StarCoder2", "mamba": "Mamba",
}

COMMANDS = [
    "/help", "/settings", "/set", "/theme", "/themes", "/preset", "/system",
    "/grounded", "/persona", "/remember", "/memories", "/forget", "/mode",
    "/temp", "/maxtokens", "/markdown", "/models", "/switch", "/recommend",
    "/save", "/load", "/sessions", "/export", "/clear", "/undo", "/regen",
    "/tokens", "/stats", "/model", "/about", "/quit",
]

DEFAULTS: Dict[str, Any] = {
    "model": {
        "threads": 0,
        "precision": "auto",
        "compile": False,
        "engine": "auto",
        "gpu_layers": -1,
        "seed": -1,
    },
    "sampling": {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "min_p": 0.05,
        "typical_p": 1.0,
        "repetition_penalty": 1.1,
    },
    "chat": {
        "max_tokens": 512,
        "mode": "normal",
        "system_preset": "balanced",
        "system_prompt": "",
        "personalization": True,
        "auto_resume": True,
        "context_budget": 0.85,
        "stop": [],
        "stream": True,
    },
    "ui": {
        "theme": "aurora",
        "markdown": True,
        "code_theme": "monokai",
        "timestamps": False,
        "user_name": "You",
        "bot_name": "Wander",
        "box": "rounded",
        "width": 100,
        "spinner": "dots12",
        "sound": False,
        "show_speed": True,
    },
    "grounding": {
        "enabled": True,
        "strict": False,
    },
}

RESTART_KEYS = {"model.precision", "model.threads", "model.compile",
                "model.engine", "model.gpu_layers"}

RANGES: Dict[str, Any] = {
    "sampling.temperature": (0.0, 2.0),
    "sampling.top_p": (0.0, 1.0),
    "sampling.min_p": (0.0, 1.0),
    "sampling.typical_p": (0.0, 1.0),
    "sampling.repetition_penalty": (0.5, 3.0),
    "chat.max_tokens": (1, 100000),
    "chat.context_budget": (0.1, 0.99),
    "ui.width": (40, 400),
}


THEMES: Dict[str, Dict[str, Any]] = {
    "aurora": {
        "primary": "#22d3ee", "accent": "#a78bfa", "user": "#34d399",
        "bot": "#818cf8", "dim": "#64748b", "warn": "#fbbf24",
        "error": "#f87171", "good": "#4ade80",
        "gradient": ["#22d3ee", "#60a5fa", "#a78bfa", "#f472b6"],
    },
    "cyberpunk": {
        "primary": "#00f0ff", "accent": "#ff2ec4", "user": "#00ff9f",
        "bot": "#ff2ec4", "dim": "#6b7280", "warn": "#ffe14d",
        "error": "#ff5555", "good": "#00ff9f",
        "gradient": ["#00f0ff", "#4d7cff", "#b537f2", "#ff2ec4"],
    },
    "forest": {
        "primary": "#34d399", "accent": "#a3e635", "user": "#86efac",
        "bot": "#4ade80", "dim": "#6b7f6b", "warn": "#facc15",
        "error": "#f87171", "good": "#a3e635",
        "gradient": ["#166534", "#22c55e", "#84cc16", "#facc15"],
    },
    "sunset": {
        "primary": "#fb923c", "accent": "#e879f9", "user": "#fbbf24",
        "bot": "#fb7185", "dim": "#8a7f72", "warn": "#fbbf24",
        "error": "#ef4444", "good": "#a3e635",
        "gradient": ["#f97316", "#fb7185", "#e879f9", "#fbbf24"],
    },
    "ocean": {
        "primary": "#38bdf8", "accent": "#2dd4bf", "user": "#2dd4bf",
        "bot": "#818cf8", "dim": "#64748b", "warn": "#fbbf24",
        "error": "#f87171", "good": "#34d399",
        "gradient": ["#0ea5e9", "#38bdf8", "#818cf8", "#2dd4bf"],
    },
    "rose": {
        "primary": "#f472b6", "accent": "#c084fc", "user": "#fda4af",
        "bot": "#e879f9", "dim": "#8b7f8b", "warn": "#fbbf24",
        "error": "#f87171", "good": "#86efac",
        "gradient": ["#fda4af", "#f472b6", "#e879f9", "#c084fc"],
    },
    "gold": {
        "primary": "#fbbf24", "accent": "#f59e0b", "user": "#fde68a",
        "bot": "#f59e0b", "dim": "#8a8272", "warn": "#fb923c",
        "error": "#f87171", "good": "#a3e635",
        "gradient": ["#b45309", "#f59e0b", "#fbbf24", "#fde68a"],
    },
    "mono": {
        "primary": "#e5e5e5", "accent": "#a3a3a3", "user": "#d4d4d4",
        "bot": "#fafafa", "dim": "#737373", "warn": "#d4d4d4",
        "error": "#fca5a5", "good": "#d4d4d4",
        "gradient": ["#737373", "#a3a3a3", "#d4d4d4", "#fafafa"],
    },
    "sakura": {
        "primary": "#f9a8d4", "accent": "#c084fc", "user": "#fda4af",
        "bot": "#f472b6", "dim": "#9d8a94", "warn": "#fbbf24",
        "error": "#f87171", "good": "#86efac",
        "gradient": ["#fecdd3", "#fda4af", "#f472b6", "#c084fc"],
    },
    "midnight": {
        "primary": "#818cf8", "accent": "#38bdf8", "user": "#67e8f9",
        "bot": "#a5b4fc", "dim": "#5b6b84", "warn": "#fbbf24",
        "error": "#f87171", "good": "#34d399",
        "gradient": ["#38bdf8", "#6366f1", "#a855f7", "#ec4899"],
    },
}

BOX_STYLES = {
    "rounded": rbox.ROUNDED, "heavy": rbox.HEAVY, "double": rbox.DOUBLE,
    "square": rbox.SQUARE, "simple": rbox.SIMPLE, "minimal": rbox.MINIMAL,
    "none": None,
}

PRESETS: Dict[str, str] = {
    "balanced": (
        "You are a helpful, knowledgeable assistant running fully offline on "
        "the user's own hardware. Be clear, structured and practical."
    ),
    "grounded": (
        "You are a precise, honest assistant running fully offline on the "
        "user's own hardware. Answer only what you are confident is true. "
        "Never invent facts, citations, names, numbers or dates. If you are "
        "unsure or lack information, say so plainly. Be concise and "
        "structured."
    ),
    "creative": (
        "You are a vivid, imaginative writer-assistant running offline on "
        "the user's hardware. Be expressive and original, but still honest: "
        "when stating real-world facts you are unsure about, flag it."
    ),
    "coder": (
        "You are an expert software engineer running offline on the user's "
        "hardware. Provide correct, idiomatic, well-commented code as plain "
        "text. Explain trade-offs briefly. Never invent APIs or libraries "
        "you are not sure exist — say so instead."
    ),
    "concise": (
        "You are a terse assistant. Answer in as few words as possible while "
        "remaining complete and honest. No filler, no preamble."
    ),
}

GROUNDING_ADDENDUM = (
    "\n\nHonesty rules — follow strictly:\n"
    "- Never fabricate facts, sources, names, numbers, URLs or dates.\n"
    "- If you are not sure, say \"I don't know\" or state your uncertainty explicitly.\n"
    "- Separate fact from inference; label speculation as speculation.\n"
    "- Prefer fewer, reliable claims over many uncertain ones.\n"
    "- You have NO internet access and your knowledge has a training cutoff. "
    "If asked about current news, recent events or \"what's new\", say you "
    "are offline and don't know — never invent updates.\n"
    "- If the question is ambiguous, ask one short clarifying question."
)
GROUNDING_STRICT_EXTRA = (
    "\n- When uncertain, default to declining or asking instead of guessing.\n"
    "- Never produce confident-sounding guesses."
)

PLAIN_TEXT_RULE = (
    "\n\nFormatting rules — strict, always follow:\n"
    "- NEVER use markdown in replies. No headings, no # symbols, no "
    "asterisks, no bold or italic markers, no backticks, no code fences, "
    "no markdown tables, no bullet lists with -, * or +.\n"
    "- Write plain text only: normal sentences and short paragraphs. "
    "If a list is truly necessary, use plain numbers (1. 2. 3.).\n"
    "- If you must show code, show it as plain text without fences or "
    "syntax markup."
)

REASONING_RULE = (
    "\n\nReasoning mode: think the problem through carefully, step by "
    "step, before giving your final answer. Show the essential steps "
    "briefly in plain text, then state the answer clearly."
)

IDENTITY_RULE = (
    "Never introduce yourself and never talk about who or what you are "
    "unless the user asks you directly. Answer only what is asked."
)

IDENTITY_TRIGGERS = (
    "who are you", "what are you", "your name", "about yourself",
    "which model", "what model", "who made you", "who created you",
    "are you an ai", "are you ai", "introduce yourself",
    "tell me about you", "what is wander", "about wander",
    "how do you work", "what engine", "your version",
)


def asks_identity(messages: List[Dict[str, str]]) -> bool:
    for m in reversed(messages):
        if m["role"] == "user":
            t = m["content"].lower()
            return any(k in t for k in IDENTITY_TRIGGERS)
    return False

MODES: Dict[str, Dict[str, Any]] = {
    "flash": {
        "temperature": 0.2, "top_p": 0.6, "top_k": 20, "min_p": 0.1,
        "max_tokens": 128,
        "blurb": "fastest — short, snappy answers",
    },
    "normal": {
        "blurb": "balanced — uses your tuned sampling settings",
    },
    "reasoning": {
        "temperature": 0.4, "top_p": 0.95, "top_k": 40, "min_p": 0.05,
        "max_tokens": 1024,
        "blurb": "deepest — thinks step by step, longer answers",
    },
}


def load_personalization() -> str:
    try:
        raw = PERSONA_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = [l.rstrip() for l in raw.splitlines()
             if l.strip() and not l.strip().startswith("#")]
    return "\n".join(lines).strip()


def load_memories() -> List[str]:
    try:
        lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
        return [l.strip() for l in lines if l.strip()]
    except OSError:
        return []


def save_memories(mems: List[str]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text("\n".join(mems[:100]) + "\n",
                               encoding="utf-8")
    except OSError:
        pass


def ensure_persona_template() -> bool:
    if PERSONA_FILE.exists():
        return False
    try:
        PERSONA_FILE.write_text(PERSONA_TEMPLATE, encoding="utf-8")
        return True
    except OSError:
        return False


_GPU_CACHE: Optional[str] = None


def detect_gpu() -> str:
    global _GPU_CACHE
    if _GPU_CACHE is not None:
        return _GPU_CACHE
    name = "none"
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController).Name -join '|'"],
                capture_output=True, text=True, timeout=15)
            for n in out.stdout.split("|"):
                low = n.strip().lower()
                if any(k in low for k in ("nvidia", "geforce", "rtx",
                                          "gtx", "radeon")):
                    name = n.strip()
                    break
        else:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                name = out.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    _GPU_CACHE = name
    return name


_SYS_CACHE: Optional[Dict[str, Any]] = None
_TURBO_FLAG: Optional[bool] = None


def turbo_installed() -> bool:
    global _TURBO_FLAG
    if _TURBO_FLAG is None:
        try:
            import importlib.util
            _TURBO_FLAG = importlib.util.find_spec("llama_cpp") is not None
        except Exception:
            _TURBO_FLAG = False
    return _TURBO_FLAG


def system_info() -> Dict[str, Any]:
    global _SYS_CACHE
    if _SYS_CACHE is not None:
        return _SYS_CACHE
    ram = 0
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_PhysicalMemory | Measure-Object "
                 "-Property Capacity -Sum).Sum"],
                capture_output=True, text=True, timeout=10)
            ram = int(out.stdout.strip())
        else:
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        ram = int(line.split()[1]) * 1024
                        break
    except Exception:
        pass
    _SYS_CACHE = {"ram": ram, "cores": os.cpu_count() or 4,
                  "gpu": detect_gpu()}
    return _SYS_CACHE


def estimate_ram(m: ModelInfo) -> int:
    quant_need = int(m.size * 1.25) + 300 * 1024 * 1024
    if turbo_installed():
        return quant_need
    if m.params:
        return int(m.params * 4) + 500 * 1024 * 1024
    return quant_need


def evaluate_models(models: List[ModelInfo]) -> Any:
    info = system_info()
    budget = int(info["ram"] * 0.6)
    results = []
    for m in models:
        need = estimate_ram(m)
        if budget <= 0:
            fit, fits = "?", True
        else:
            ratio = need / budget
            if ratio <= 0.5:
                fit = "comfortable"
            elif ratio <= 1.0:
                fit = "ok"
            elif ratio <= 1.25:
                fit = "tight"
            else:
                fit = "too big"
            fits = ratio <= 1.0
        score = 40.0 if m.instruct else -25.0
        if m.params:
            score += min(m.params / 1e9, 8.0) * 6
        q = m.quant.upper()
        if q.startswith(("Q8", "Q6", "F16")):
            score += 8
        elif q.startswith("Q5"):
            score += 5
        elif q.startswith("Q4"):
            score += 3
        if fit == "comfortable":
            score += 15
        elif fit == "ok":
            score += 8
        elif fit == "tight":
            score -= 10
        elif fit == "too big":
            score -= 60
        if m.ctx and m.ctx < 2048:
            score -= 10
        results.append({"model": m, "fit": fit, "fits": fits,
                        "need": need, "score": score})
    fitting = [r for r in results if r["fits"]]
    best = max(fitting, key=lambda r: r["score"]) if fitting else None
    return results, best, info


def boot_log(msg: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "boot.log", "a", encoding="utf-8") as fh:
            fh.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "  "
                     + msg + "\n")
    except OSError:
        pass


def deep_merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def flatten_keys(d: Dict[str, Any], prefix: str = "") -> List[str]:
    out: List[str] = []
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.extend(flatten_keys(v, path))
        else:
            out.append(path)
    return out


def cfg_get(cfg: Dict[str, Any], path: str) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def cfg_set(cfg: Dict[str, Any], path: str, raw: str) -> Any:
    parts = path.split(".")
    cur = cfg
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            raise KeyError(path)
        cur = cur[p]
    last = parts[-1]
    if last not in cur:
        raise KeyError(path)
    current = cur[last]
    try:
        if isinstance(current, bool):
            val: Any = raw.strip().lower() in ("1", "true", "on", "yes", "y", "t")
        elif isinstance(current, int):
            val = int(raw)
        elif isinstance(current, float):
            val = float(raw)
        elif isinstance(current, list):
            val = [s.strip() for s in raw.split(",") if s.strip()]
        else:
            val = raw
    except ValueError:
        raise ValueError(f"could not parse {raw!r} for {path}")
    bounds = RANGES.get(path)
    if bounds and isinstance(val, (int, float)) and not isinstance(val, bool):
        lo, hi = bounds
        if not (lo <= val <= hi):
            raise ValueError(f"{path} must be between {lo} and {hi}")
    cur[last] = val
    return val


def toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        if "\n" in v:
            esc = v.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
            return '"""\n' + esc + '\n"""'
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return toml_value(str(v))


def save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# ✦ wander configuration — everything lives in this folder",
        "# change live with:  /set key value",
        "",
    ]
    for section in ("model", "sampling", "chat", "ui", "grounding"):
        lines.append(f"[{section}]")
        for k, v in cfg.get(section, {}).items():
            lines.append(f"{k} = {toml_value(v)}")
        lines.append("")
    CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8")


def sanitize_config(cfg: Dict[str, Any]) -> None:
    def walk(default: Dict[str, Any], cur: Dict[str, Any]) -> None:
        for k in list(cur):
            if k not in default:
                del cur[k]
        for k, dv in default.items():
            cv = cur.get(k)
            if isinstance(dv, dict):
                if not isinstance(cv, dict):
                    cur[k] = copy.deepcopy(dv)
                else:
                    walk(dv, cv)
                continue
            if cv is None or (isinstance(cv, dict)
                              and not isinstance(dv, dict)):
                cur[k] = copy.deepcopy(dv)
                continue
            if isinstance(dv, bool):
                if not isinstance(cv, bool):
                    cur[k] = dv
            elif isinstance(dv, int):
                if not isinstance(cv, int) or isinstance(cv, bool):
                    cur[k] = dv
            elif isinstance(dv, float):
                if isinstance(cv, bool) or not isinstance(cv, (int, float)):
                    cur[k] = dv
                else:
                    cur[k] = float(cv)
            elif isinstance(dv, str):
                if not isinstance(cv, str):
                    cur[k] = dv
            elif isinstance(dv, list):
                if not isinstance(cv, list):
                    cur[k] = copy.deepcopy(dv)

    walk(DEFAULTS, cfg)
    for key, (lo, hi) in RANGES.items():
        try:
            v = cfg_get(cfg, key)
        except KeyError:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool) \
                and not (lo <= v <= hi):
            parts = key.split(".")
            cur = cfg
            for p in parts[:-1]:
                cur = cur[p]
            cur[parts[-1]] = copy.deepcopy(cfg_get(DEFAULTS, key))


def load_config_file() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with open(CONFIG_PATH, "rb") as fh:
            data = tomllib.load(fh)
        cfg = deep_merge(DEFAULTS, data)
    except Exception as exc:
        sys.stderr.write(f"[wander] could not read config: {exc}\n")
        cfg = copy.deepcopy(DEFAULTS)
    sanitize_config(cfg)
    return cfg


def hex_lerp(c1: str, c2: str, t: float) -> str:
    a = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    b = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    m = [int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3)]
    return "#%02x%02x%02x" % tuple(m)


def gradient_sample(stops: List[str], t: float) -> str:
    t = max(0.0, min(1.0, t))
    segs = len(stops) - 1
    idx = min(int(t * segs), segs - 1)
    return hex_lerp(stops[idx], stops[idx + 1], (t * segs) - idx)


def hms(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.2f} TB"


def log_error(context: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {context}\n")
            traceback.print_exc(file=fh)
            fh.write("\n")
    except OSError:
        pass


def crash_panel(console: Console, exc: BaseException) -> None:
    log_error("fatal error")
    console.print(Panel(Text.assemble(
        ("Wander hit an unexpected error.\n\n", "bold"),
        (f"{type(exc).__name__}: {exc}\n\n", ""),
        ("Full details were written to ", ""),
        (str(LOG_PATH), "bold cyan"),
        ("\nIf the problem persists, include that file when asking "
         "for help.", ""),
    ), title="[bold red]✦ wander — error report[/]", border_style="red",
        box=rbox.ROUNDED))


_LETTERS = {
    "W": ["██╗    ██╗", "██║    ██║", "██║ █╗ ██║", "██║███╗██║", "╚███╔███╔╝", " ╚══╝╚══╝ "],
    "A": [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "D": ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "R": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"],
    " ": ["    ", "    ", "    ", "    ", "    ", "    "],
}


def banner_text(title: str, stops: List[str]) -> Text:
    rows = ["", "", "", "", "", ""]
    for ch in title:
        glyph = _LETTERS.get(ch.upper(), _LETTERS[" "])
        for i in range(6):
            rows[i] += glyph[i] + " "
    width = max(len(r) for r in rows)
    txt = Text(no_wrap=True)
    for i, row in enumerate(rows):
        for j, ch in enumerate(row):
            if ch == " ":
                txt.append(" ")
            else:
                txt.append(ch, style=f"bold {gradient_sample(stops, j / max(width - 1, 1))}")
        if i < 5:
            txt.append("\n")
    return txt


def show_banner(console: Console, cfg: Dict[str, Any],
                info: Dict[str, Any], demo: bool = False) -> None:
    th = THEMES.get(cfg["ui"]["theme"], THEMES["aurora"])
    bx = BOX_STYLES.get(cfg["ui"]["box"], rbox.ROUNDED)
    if console.width >= 64:
        head: Any = Align.center(banner_text("WANDER", th["gradient"]))
    else:
        head = Align.center(Text("✦ WANDER",
                                 style=f"bold {th['primary']}"))
    mode = " [demo]" if demo else ""
    tag = Align.center(Text("offline AI, anywhere",
                            style=f"italic {th['dim']}"))
    meta = Align.center(Text.assemble(
        (str(info.get("name", "—")), f"bold {th['accent']}"),
        (f"   ·   ctx {int(info.get('context', 0)):,}{mode}", th["dim"]),
    ))
    console.print()
    console.print(Panel(Group(head, Text(""), tag, Text(""), meta),
                        border_style=th["primary"],
                        box=bx, padding=(0, 1)))
    width = min(console.width, int(cfg["ui"]["width"] or 100))
    console.print(Align.center(
        gradient_rule(th["gradient"], max(width - 8, 30))))
    console.print(Text("type /help for commands · /switch to "
                       "change model · Ctrl-D to quit",
                       style=th["dim"]), justify="center")
    console.print()


def gradient_rule(stops: List[str], width: int, center: str = "✦") -> Text:
    width = max(width, 20)
    mid = width // 2
    txt = Text(no_wrap=True)
    for j in range(width):
        color = gradient_sample(stops, j / max(width - 1, 1))
        if center and j == mid:
            txt.append(center, style=f"bold {color}")
        elif center and j in (mid - 2, mid + 2):
            txt.append("◆", style=color)
        else:
            txt.append("─", style=color)
    return txt


class ModelInfo:
    def __init__(self, path: Path):
        self.path = path
        self.name = path.stem
        self.display = path.stem
        self.arch: Optional[str] = None
        self.arch_friendly = ""
        self.ctx: Optional[int] = None
        self.quant = "?"
        self.supported = False
        self.readable = False
        self.params: Optional[int] = None
        self.instruct = False
        try:
            self.size = path.stat().st_size
        except OSError:
            self.size = 0

    def load_meta(self) -> "ModelInfo":
        try:
            from gguf import GGUFReader
            reader = GGUFReader(str(self.path), "r")

            def fstr(field: str) -> Optional[str]:
                f = reader.fields.get(field)
                if f is None or not f.parts:
                    return None
                with contextlib.suppress(Exception):
                    return bytes(f.parts[-1]).decode("utf-8", "replace")
                return None

            def fint(field: str) -> Optional[int]:
                f = reader.fields.get(field)
                if f is None or not f.parts:
                    return None
                with contextlib.suppress(Exception):
                    return int(f.parts[-1][0])
                return None

            self.readable = True
            gname = fstr("general.name")
            if gname:
                self.display = gname
            self.arch = fstr("general.architecture")
            if self.arch:
                self.arch_friendly = ARCH_FRIENDLY.get(self.arch, self.arch)
                self.supported = self.arch in SUPPORTED_ARCHS
                self.ctx = fint(f"{self.arch}.context_length")

            counts: Dict[str, int] = {}
            total = 0
            for t in reader.tensors:
                key = getattr(t.tensor_type, "name", str(t.tensor_type))
                counts[key] = counts.get(key, 0) + 1
                n = 1
                for d in t.shape:
                    n *= int(d)
                total += n
            if counts:
                self.quant = max(counts.items(), key=lambda kv: kv[1])[0]
            self.params = total
        except Exception:
            self.readable = False
        hay = (self.display + " " + self.path.stem).lower()
        self.instruct = any(k in hay for k in (
            "instruct", "chat", "assistant", "-it", " it"))
        return self


def _load_models_cache() -> Dict[str, Any]:
    try:
        data = json.loads(MODELS_CACHE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_models_cache(cache: Dict[str, Any]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MODELS_CACHE.write_text(json.dumps(cache, ensure_ascii=False),
                                encoding="utf-8")
    except OSError:
        pass


def _model_from_cache(path: Path, entry: Dict[str, Any]) -> ModelInfo:
    m = ModelInfo(path)
    m.display = str(entry.get("display", path.stem))
    m.arch = entry.get("arch")
    m.arch_friendly = str(entry.get("arch_friendly", ""))
    ctx = entry.get("ctx")
    m.ctx = int(ctx) if isinstance(ctx, int) else None
    m.quant = str(entry.get("quant", "?"))
    m.readable = bool(entry.get("readable", False))
    params = entry.get("params")
    m.params = int(params) if isinstance(params, int) else None
    m.instruct = bool(entry.get("instruct", False))
    try:
        m.size = int(entry.get("size", 0))
    except (TypeError, ValueError):
        m.size = 0
    if m.arch:
        m.supported = m.arch in SUPPORTED_ARCHS
    return m


def _model_to_entry(m: ModelInfo, st: Any) -> Dict[str, Any]:
    return {
        "display": m.display, "arch": m.arch,
        "arch_friendly": m.arch_friendly, "ctx": m.ctx,
        "quant": m.quant, "readable": m.readable,
        "params": m.params, "instruct": m.instruct,
        "size": m.size, "mtime": st.st_mtime, "fsize": st.st_size,
    }


def discover_models() -> List[ModelInfo]:
    found: List[Path] = []
    if MODELS_DIR.exists():
        for p in MODELS_DIR.rglob("*"):
            if p.is_file() and p.suffix.lower() == ".gguf":
                found.append(p)
    cache = _load_models_cache()
    models: List[ModelInfo] = []
    new_cache: Dict[str, Any] = {}
    changed = False
    for p in found:
        try:
            st = p.stat()
        except OSError:
            continue
        entry = cache.get(str(p))
        if (entry and "params" in entry
                and entry.get("mtime") == st.st_mtime
                and entry.get("fsize") == st.st_size):
            models.append(_model_from_cache(p, entry))
            new_cache[str(p)] = entry
        else:
            m = ModelInfo(p).load_meta()
            models.append(m)
            new_cache[str(p)] = _model_to_entry(m, st)
            changed = True
    if changed or len(new_cache) != len(cache):
        _save_models_cache(new_cache)
    models.sort(key=lambda m: m.path.name.lower())
    return models


def save_last_model(path: Path) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LAST_MODEL_FILE.write_text(json.dumps({"path": str(path)}),
                                   encoding="utf-8")
    except OSError:
        pass


def load_last_model() -> Optional[Path]:
    try:
        data = json.loads(LAST_MODEL_FILE.read_text(encoding="utf-8"))
        p = Path(data.get("path", ""))
        return p if p.exists() else None
    except Exception:
        return None


def read_key() -> str:

    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return {"H": "up", "P": "down"}.get(ch2, "")
        if ch == "\r":
            return "enter"
        if ch == "\x1b":
            return "esc"
        return ch
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            if select.select([sys.stdin], [], [], 0.05)[0]:
                seq = sys.stdin.read(1)
                if seq == "[":
                    code = sys.stdin.read(1)
                    return {"A": "up", "B": "down"}.get(code, "")
            return "esc"
        if ch in ("\r", "\n"):
            return "enter"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def model_row_text(m: ModelInfo, th: Dict[str, Any]) -> str:
    bits = [human_size(m.size), m.quant]
    if m.arch:
        bits.append(m.arch_friendly)
    if m.ctx:
        bits.append(f"ctx {m.ctx:,}")
    if m.readable and m.arch and not m.supported:
        bits.append("⚠ arch not officially supported")
    if not m.readable:
        bits.append("⚠ metadata unreadable — will still try")
    return " · ".join(bits)


def pick_model(console: Console, cfg: Dict[str, Any],
               models: List[ModelInfo]) -> Optional[Path]:
    th = THEMES.get(cfg["ui"]["theme"], THEMES["aurora"])
    last = load_last_model()
    try:
        _, best, _ = evaluate_models(models)
    except Exception:
        best = None
    best_path = best["model"].path if best else None
    items: List[Dict[str, Any]] = []
    sel = 0
    for i, m in enumerate(models):
        try:
            is_last = (last is not None
                       and last.resolve() == m.path.resolve())
        except OSError:
            is_last = False
        label = m.display + ("   ↺ last used" if is_last else "")
        if best_path and m.path == best_path:
            label += "   ★ best for this pc"
        items.append({"label": label, "sub": model_row_text(m, th),
                      "path": m.path})
        if is_last:
            sel = i
    if not items:
        return None
    if len(items) == 1:
        return items[0]["path"]

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:

        console.print(Panel(Text.assemble(
            ("✦ pick your model", f"bold {th['primary']}"),
            (f"   ({len(items)} found in {MODELS_DIR})", f"{th['dim']}")),
            border_style=th["primary"], box=rbox.ROUNDED))
        for i, it in enumerate(items, 1):
            console.print(Text.assemble(
                (f" {i}. ", f"bold {th['accent']}"),
                (it["label"], "bold"),
                (f"   {it['sub']}", f"{th['dim']}")))
        while True:
            try:
                raw = input(f"enter a number [1]: ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                return None
            if raw.isdigit() and 1 <= int(raw) <= len(items):
                return items[int(raw) - 1]["path"]
            console.print(Text("type a number from the list",
                               style=th["warn"]))

    sel = 0
    def render() -> Panel:
        body = Text()
        body.append(f"✦ WANDER found {len(items)} model(s) in models/ — "
                    "choose one\n\n",
                    style=f"bold {th['primary']}")
        for i, it in enumerate(items):
            active = i == sel
            pointer = "❯ " if active else "  "
            body.append(pointer, style=f"bold {th['primary']}" if active else th["dim"])
            body.append(f"{i + 1}. {it['label']}",
                        style=f"bold {th['primary']}" if active else "bold")
            body.append("\n")
            body.append(f"      {it['sub']}\n", style=th["dim"])
        body.append("\n↑↓ or j/k to move · Enter to select · number for "
                    "quick pick · q to quit", style=f"italic {th['dim']}")
        deco = Align.center(gradient_rule(th["gradient"], 56))
        return Panel(Group(deco, Text(""), body),
                     border_style=th["primary"], box=rbox.ROUNDED,
                     title=f"[{th['primary']}]✦[/] [bold]model "
                           "selection[/]", title_align="left")

    try:
        with Live(render(), console=console, screen=False,
                  refresh_per_second=30) as live:
            while True:
                key = read_key()
                if key in ("up", "k"):
                    sel = (sel - 1) % len(items)
                elif key in ("down", "j"):
                    sel = (sel + 1) % len(items)
                elif key == "enter":
                    return items[sel]["path"]
                elif key.isdigit() and 1 <= int(key) <= len(items):
                    return items[int(key) - 1]["path"]
                elif key in ("q", "esc", "\x03"):
                    return None
                live.update(render())
    except Exception:

        for i, it in enumerate(items, 1):
            console.print(f" {i}. {it['label']}   ({it['sub']})")
        try:
            raw = input("enter a number [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            return items[int(raw) - 1]["path"]
        return None


class MockBackend:


    def __init__(self, cfg: Dict[str, Any]):
        self._ctx = 4096
        self.last_usage: Optional[Dict[str, int]] = None

    @property
    def n_ctx(self) -> int:
        return self._ctx

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def stream(self, messages: List[Dict[str, str]],
               params: Dict[str, Any]) -> Iterator[str]:
        user = ""
        for m in reversed(messages):
            if m["role"] == "user":
                user = m["content"]
                break
        reply = (
            "Demo mode — no real model is loaded.\n\n"
            f"You said: {user}\n\n"
            "To chat for real, drop one or more .gguf files into the "
            "models/ folder next to wander.py and start Wander again. "
            "You'll get a nice model-selection screen.\n\n"
            "Meanwhile, explore: /themes, /set, /settings, /help."
        )
        tokens = reply.split(" ")
        for i, w in enumerate(tokens):
            time.sleep(0.012)
            yield w + (" " if i < len(tokens) - 1 else "")
        self.last_usage = {"completion_tokens": len(tokens)}

    @property
    def info(self) -> Dict[str, Any]:
        return {"name": "demo-echo (no model)", "path": "—", "size": "—",
                "context": self._ctx, "quant": "—", "precision": "—",
                "backend": "mock"}

    def close(self) -> None:
        pass


class TransformersBackend:


    def __init__(self, cfg: Dict[str, Any], model_path: Path,
                 meta: ModelInfo):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, \
            TextIteratorStreamer
        self.torch = torch
        self._streamer_cls = TextIteratorStreamer
        self.path = Path(model_path)
        self.meta = meta
        self.last_usage: Optional[Dict[str, int]] = None

        threads = int(cfg["model"]["threads"])
        if threads > 0:
            torch.set_num_threads(threads)
            with contextlib.suppress(Exception):
                torch.set_num_interop_threads(max(1, threads // 2))


        prec = str(cfg["model"]["precision"]).lower()
        if prec == "auto":
            prec = "fp32" if meta.size <= 2.4 * 1024 ** 3 else "fp16"
        dtype = {"fp32": torch.float32, "fp16": torch.float16,
                 "bf16": torch.bfloat16}.get(prec, torch.float32)
        self.precision = prec

        directory = str(self.path.parent)
        fname = self.path.name
        self.tokenizer = AutoTokenizer.from_pretrained(directory,
                                                       gguf_file=fname)

        try:
            self.model = AutoModelForCausalLM.from_pretrained(
                directory, gguf_file=fname, dtype=dtype,
                low_cpu_mem_usage=True)
        except TypeError:
            self.model = AutoModelForCausalLM.from_pretrained(
                directory, gguf_file=fname, torch_dtype=dtype,
                low_cpu_mem_usage=True)
        self.model.eval()
        self.device = "cpu"
        if torch.cuda.is_available():
            with contextlib.suppress(Exception):
                self.model.to("cuda")
                self.device = "cuda"
        if cfg["model"].get("compile"):
            with contextlib.suppress(Exception):
                self.model = torch.compile(self.model)
        self._ctx = meta.ctx or 4096

    @property
    def n_ctx(self) -> int:
        return self._ctx

    def count_tokens(self, text: str) -> int:
        try:
            return len(self.tokenizer(text, add_special_tokens=False)
                       ["input_ids"])
        except Exception:
            return max(1, len(text) // 4)

    def render_chat(self, messages: List[Dict[str, str]]) -> str:
        tk = self.tokenizer
        if getattr(tk, "chat_template", None):
            try:
                return tk.apply_chat_template(messages, tokenize=False,
                                              add_generation_prompt=True)
            except Exception:
                pass
        parts: List[str] = []
        for m in messages:
            if m["role"] == "system":
                parts.append(m["content"] + "\n\n")
            elif m["role"] == "user":
                parts.append(f"User: {m['content']}\n")
            else:
                parts.append(f"Assistant: {m['content']}\n")
        parts.append("Assistant:")
        return "".join(parts)

    def sampling_kwargs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        kw: Dict[str, Any] = {
            "max_new_tokens": int(params["max_tokens"]),
        }
        pad = self.tokenizer.pad_token_id
        if pad is None:
            pad = self.tokenizer.eos_token_id
        if pad is not None:
            kw["pad_token_id"] = pad
        temp = float(params["temperature"])
        if temp <= 0:
            kw["do_sample"] = False
            return kw
        kw.update({
            "do_sample": True,
            "temperature": temp,
            "top_p": float(params["top_p"]),
            "top_k": int(params["top_k"]),
            "min_p": float(params["min_p"]),
            "typical_p": float(params["typical_p"]),
            "repetition_penalty": float(params["repetition_penalty"]),
        })
        return kw

    def stream(self, messages: List[Dict[str, str]],
               params: Dict[str, Any]) -> Iterator[str]:
        import threading
        self.last_usage = None
        torch = self.torch
        seed = int(params.get("seed", -1))
        if seed >= 0:
            torch.manual_seed(seed)

        prompt = self.render_chat(messages)
        enc = self.tokenizer(prompt, return_tensors="pt", truncation=True,
                             max_length=max(self.n_ctx - 4, 16))
        gen_kwargs: Dict[str, Any] = dict(
            input_ids=enc["input_ids"].to(self.model.device),
            attention_mask=(enc["attention_mask"].to(self.model.device)
                            if enc.get("attention_mask") is not None
                            else None),
            streamer=self._streamer_cls(self.tokenizer, skip_prompt=True,
                                        skip_special_tokens=True),
            **self.sampling_kwargs(params),
        )
        stops = params.get("stop") or []
        if stops:
            with contextlib.suppress(TypeError):
                gen_kwargs["stop_strings"] = list(stops)
                gen_kwargs["tokenizer"] = self.tokenizer

        error: List[BaseException] = []

        def _run() -> None:
            try:
                with torch.inference_mode():
                    self.model.generate(**gen_kwargs)
            except BaseException as exc:
                error.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        streamer = gen_kwargs["streamer"]
        generated = ""
        try:
            for piece in streamer:
                generated += piece
                yield piece
        finally:
            thread.join()
        if error:
            raise error[0]
        self.last_usage = {"completion_tokens": self.count_tokens(generated)}

    @property
    def info(self) -> Dict[str, Any]:
        m = self.meta
        return {
            "name": m.display,
            "file": self.path.name,
            "size": human_size(m.size),
            "context": self.n_ctx,
            "quant": m.quant,
            "arch": m.arch_friendly or m.arch or "?",
            "precision": self.precision,
            "backend": "transformers (pytorch)",
            "device": getattr(self, "device", "cpu"),
        }

    def close(self) -> None:
        with contextlib.suppress(Exception):
            del self.model


def _create_llama(cfg: Dict[str, Any], path: Path, meta: ModelInfo) -> Any:
    from llama_cpp import Llama
    threads = int(cfg["model"]["threads"]) or None
    base = dict(
        model_path=str(path),
        n_ctx=int(meta.ctx or 4096),
        n_batch=2048,
        n_threads=threads,
        n_gpu_layers=int(cfg["model"].get("gpu_layers", -1)),
        use_mmap=True,
        verbose=False,
    )
    attempts = [
        dict(flash_attn=True, type_k="q8_0", type_v="q8_0"),
        dict(type_k="q8_0", type_v="q8_0"),
        dict(flash_attn=True),
        {},
    ]
    last_exc: Optional[BaseException] = None
    for extra in attempts[:-1]:
        try:
            return Llama(**extra, **base)
        except Exception as exc:
            last_exc = exc
    try:
        return Llama(**base)
    except Exception:
        if last_exc is not None:
            raise last_exc
        raise


class TurboBackend:
    def __init__(self, cfg: Dict[str, Any], model_path: Path,
                 meta: ModelInfo):
        self.path = Path(model_path)
        self.meta = meta
        self.last_usage: Optional[Dict[str, int]] = None
        self.llm = _create_llama(cfg, self.path, meta)
        self._ctx = int(meta.ctx or 4096)

    @property
    def n_ctx(self) -> int:
        try:
            return int(self.llm.n_ctx())
        except Exception:
            return self._ctx

    def count_tokens(self, text: str) -> int:
        try:
            return len(self.llm.tokenize(text.encode("utf-8"),
                                         add_bos=False))
        except Exception:
            return max(1, len(text) // 4)

    def stream(self, messages: List[Dict[str, str]],
               params: Dict[str, Any]) -> Iterator[str]:
        self.last_usage = None
        kw: Dict[str, Any] = {
            "temperature": max(float(params["temperature"]), 0.0),
            "top_p": float(params["top_p"]),
            "top_k": int(params["top_k"]),
            "min_p": float(params["min_p"]),
            "typical_p": float(params["typical_p"]),
            "repeat_penalty": float(params["repetition_penalty"]),
            "max_tokens": int(params["max_tokens"]),
        }
        seed = int(params.get("seed", -1))
        if seed >= 0:
            kw["seed"] = seed
        if params.get("stop"):
            kw["stop"] = list(params["stop"])
        try:
            try:
                chunks = self.llm.create_chat_completion(
                    messages=messages, stream=True,
                    stream_options={"include_usage": True}, **kw)
            except TypeError:
                chunks = self.llm.create_chat_completion(
                    messages=messages, stream=True, **kw)
            for chunk in chunks:
                if chunk.get("usage"):
                    self.last_usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    yield piece
        except (NotImplementedError, ValueError):
            yield from self._stream_plain(messages, kw)

    def _stream_plain(self, messages: List[Dict[str, str]],
                     kw: Dict[str, Any]) -> Iterator[str]:
        parts: List[str] = []
        for mrec in messages:
            if mrec["role"] == "system":
                parts.append(mrec["content"] + "\n\n")
            elif mrec["role"] == "user":
                parts.append(f"User: {mrec['content']}\n")
            else:
                parts.append(f"Assistant: {mrec['content']}\n")
        parts.append("Assistant:")
        safe = {k: v for k, v in kw.items() if k in (
            "temperature", "top_p", "top_k", "repeat_penalty",
            "max_tokens", "stop", "seed")}
        for chunk in self.llm.create_completion(prompt="".join(parts),
                                                stream=True, **safe):
            choices = chunk.get("choices") or []
            if choices and choices[0].get("text"):
                yield choices[0]["text"]

    @property
    def info(self) -> Dict[str, Any]:
        m = self.meta
        return {
            "name": m.display,
            "file": self.path.name,
            "size": human_size(m.size),
            "context": self.n_ctx,
            "quant": m.quant,
            "arch": m.arch_friendly or m.arch or "?",
            "precision": "quantized (native)",
            "backend": "llama.cpp (turbo)",
            "gpu": detect_gpu(),
            "gpu offload": ("auto — used when a GPU engine build is "
                            "installed"),
        }

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.llm.close()


class Conversation:
    def __init__(self) -> None:
        self.messages: List[Dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def pop_last_assistant(self) -> Optional[Dict[str, str]]:
        if self.messages and self.messages[-1]["role"] == "assistant":
            return self.messages.pop()
        return None

    def undo(self) -> List[Dict[str, str]]:
        removed: List[Dict[str, str]] = []
        if self.messages and self.messages[-1]["role"] == "assistant":
            removed.append(self.messages.pop())
        if self.messages and self.messages[-1]["role"] == "user":
            removed.append(self.messages.pop())
        return removed

    def clear(self) -> None:
        self.messages = []

    @property
    def turns(self) -> int:
        return sum(1 for m in self.messages if m["role"] == "user")

    def to_dict(self) -> Dict[str, Any]:
        return {"version": 1,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "messages": self.messages}

    def load_dict(self, data: Dict[str, Any]) -> None:
        msgs = data.get("messages", [])
        self.messages = [m for m in msgs
                         if isinstance(m, dict) and m.get("role") in
                         ("user", "assistant")
                         and isinstance(m.get("content"), str)]


class ChatApp:
    def __init__(self, cfg: Dict[str, Any], backend: Any) -> None:
        self.cfg = cfg
        self.backend = backend
        self.convo = Conversation()
        self.console = Console(highlight=False,
                               width=cfg["ui"]["width"] or None)
        self.started = time.time()
        self.gen_count = 0
        self.gen_tokens = 0
        self.gen_seconds = 0.0
        self._tok_cache: Dict[str, int] = {}

        self.model_chooser: Optional[Callable[[], Optional[Path]]] = None
        self.backend_builder: Optional[Callable[[Path], Any]] = None
        self.persona_note = ""
        self.banner_shown = False
        self.prompt_session = self._make_prompt_session()


    @property
    def th(self) -> Dict[str, Any]:
        return THEMES.get(self.cfg["ui"]["theme"], THEMES["aurora"])

    @property
    def box(self) -> Any:
        return BOX_STYLES.get(self.cfg["ui"]["box"], rbox.ROUNDED)


    def _make_prompt_session(self) -> Any:
        if not sys.stdin.isatty():
            return None
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.completion import WordCompleter
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.key_binding import KeyBindings
        except ImportError:
            return None
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        kb = KeyBindings()

        @kb.add("c-m")
        def _submit(event: Any) -> None:
            event.current_buffer.validate_and_handle()

        @kb.add("escape", "enter")
        @kb.add("c-j")
        def _newline(event: Any) -> None:
            event.current_buffer.insert_text("\n")

        th = self.th
        return PromptSession(
            history=FileHistory(str(HISTORY_FILE)),
            multiline=True,
            key_bindings=kb,
            completer=WordCompleter(COMMANDS, sentence=True),
            complete_while_typing=False,
            prompt_continuation=Text("⋮ ", style=th["dim"]),
        )

    def read_input(self) -> str:
        if self.prompt_session is not None:
            from prompt_toolkit.formatted_text import HTML
            th = self.th
            msg = HTML(f'<b style="fg:{th["user"]}">❯ </b>')
            return self.prompt_session.prompt(msg)
        return input(f'{self.cfg["ui"]["user_name"]}> ')

    def _erase_echo(self, text: str) -> None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return
        try:
            width = shutil.get_terminal_size((80, 24)).columns
        except Exception:
            width = 80
        width = max(width, 1)
        prefix = (2 if self.prompt_session is not None
                  else len(self.cfg["ui"]["user_name"]) + 2)
        total = 0
        for part in text.split("\n"):
            total += max(1, math.ceil((len(part) + prefix) / width))
        seq = (f"\x1b[{total}A" + "\x1b[2K\x1b[1B" * total
               + f"\x1b[{total}A")
        with contextlib.suppress(Exception):
            sys.stdout.write(seq)
            sys.stdout.flush()


    def count(self, text: str) -> int:
        cached = self._tok_cache.get(text)
        if cached is None:
            cached = self.backend.count_tokens(text)
            if len(self._tok_cache) > 4096:
                self._tok_cache.clear()
            self._tok_cache[text] = cached
        return cached

    def _context_tokens(self) -> int:
        total = 4 + self.count(self.build_system())
        for m in self.convo.messages:
            total += 4 + self.count(m["content"])
        return total

    def build_system(self) -> str:
        c = self.cfg
        preset = PRESETS.get(c["chat"]["system_preset"], PRESETS["balanced"])
        base = (c["chat"]["system_prompt"] or "").strip() or preset
        base += "\n\n" + IDENTITY_RULE
        if c["chat"].get("personalization", True):
            persona = load_personalization()
            if persona:
                base += ("\n\nPersonalization — apply to every reply:\n"
                         + persona)
        mems = load_memories()
        if mems:
            base += ("\n\nLong-term memory — things you already know from "
                     "earlier conversations, use them naturally:\n"
                     + "\n".join("- " + m for m in mems[:50]))
        base += PLAIN_TEXT_RULE
        if asks_identity(self.convo.messages):
            base += self._identity_facts()
        if str(c["chat"].get("mode", "normal")).lower() == "reasoning":
            base += REASONING_RULE
        if c["grounding"]["enabled"]:
            base += GROUNDING_ADDENDUM
            if c["grounding"]["strict"]:
                base += GROUNDING_STRICT_EXTRA
        base += "\n\nReminder — " + IDENTITY_RULE
        return base

    def _identity_facts(self) -> str:
        info = self.backend.info
        return (
            "\n\nThe user is asking about you. Answer briefly and honestly "
            "using only these facts:\n"
            f"- You are Wander, a portable, fully offline "
            "terminal AI that lives entirely inside one folder (usually on "
            "a pendrive). Nothing about you is installed on the computer.\n"
            f"- Your engine is {info.get('backend', 'transformers')} and "
            f"you are currently running the model "
            f"\"{info.get('name', 'unknown')}\" "
            f"(size {info.get('size', '?')}, "
            f"context {info.get('context', '?')} tokens).\n"
            "- You have no internet access and no tools: you cannot search, "
            "browse, or run anything. Your knowledge comes only from your "
            "training data.\n"
            "- The user can switch you to a different model with /switch; "
            "your memories do not transfer between models.\n"
            "- Answer questions about yourself honestly using these facts, "
            "and never claim abilities you do not have. After answering, "
            "return to normal conversation."
        )

    def fit_context(self, history: List[Dict[str, str]],
                    reserve_out: int) -> List[Dict[str, str]]:
        ctx = self.backend.n_ctx or 4096
        budget = int(ctx * float(self.cfg["chat"]["context_budget"]))
        avail = budget - self.count(self.build_system()) - reserve_out
        msgs = list(history)

        def total(ms: List[Dict[str, str]]) -> int:
            return sum(4 + self.count(m["content"]) for m in ms)

        dropped = 0
        trimmed: List[Dict[str, str]] = []
        while msgs and total(msgs) > max(avail, 64):
            trimmed.append(msgs.pop(0))
            dropped += 1
        if dropped:
            self._preserve_trimmed(trimmed)
            self.console.print(Text(f"⚠ context nearly full — trimmed "
                                    f"{dropped} oldest message(s) "
                                    f"(saved to memory)",
                                    style=self.th["warn"]))
        return msgs

    def _preserve_trimmed(self, trimmed: List[Dict[str, str]]) -> None:
        try:
            topics = []
            for m in trimmed:
                if m["role"] == "user":
                    t = " ".join(m["content"].split())
                    if t:
                        topics.append(t[:120])
            if not topics:
                return
            mems = load_memories()
            recap = "[earlier] " + " · ".join(topics[-5:])
            mems = [x for x in mems
                    if not x.startswith("[earlier] ")]
            mems.append(recap[:400])
            save_memories(mems)
        except Exception:
            pass

    def cmd_remember(self, arg: str) -> None:
        if not arg:
            self.note("usage: /remember <something to remember>", "warn")
            return
        mems = load_memories()
        mems.append(arg.strip())
        save_memories(mems)
        self.note(f"✓ remembered — {len(mems)} memories stored", "good")

    def cmd_memories(self) -> None:
        mems = load_memories()
        if not mems:
            self.note("no memories yet — use /remember <text> to add one",
                      "dim")
            return
        t = Table(title="✦ long-term memory", border_style=self.th["primary"],
                  box=self.box, show_edge=False)
        t.add_column("#", justify="right", style=self.th["accent"])
        t.add_column("memory")
        for i, m in enumerate(mems, 1):
            t.add_row(str(i), m)
        self.console.print(t)
        self.note("/remember <text> to add · /forget <#> to remove", "dim")

    def cmd_forget(self, arg: str) -> None:
        mems = load_memories()
        if not arg.isdigit() or not (1 <= int(arg) <= len(mems)):
            self.note("usage: /forget <number> — see /memories", "warn")
            return
        gone = mems.pop(int(arg) - 1)
        save_memories(mems)
        self.note(f"✓ forgot: {gone[:60]}", "good")

    def sampling_params(self) -> Dict[str, Any]:
        s, c, m = self.cfg["sampling"], self.cfg["chat"], self.cfg["model"]
        profile = MODES.get(str(c.get("mode", "normal")).lower(), {})
        temp = float(profile.get("temperature", s["temperature"]))
        top_p = float(profile.get("top_p", s["top_p"]))
        top_k = int(profile.get("top_k", s["top_k"]))
        min_p = float(profile.get("min_p", s["min_p"]))
        max_tokens = int(profile.get("max_tokens", c["max_tokens"]))
        g = self.cfg["grounding"]
        if g["enabled"] and g["strict"]:
            temp = min(temp, 0.5)
            top_p = min(top_p, 0.9)
        return {
            "temperature": temp,
            "top_p": top_p,
            "top_k": top_k,
            "min_p": min_p,
            "typical_p": float(s["typical_p"]),
            "repetition_penalty": float(s["repetition_penalty"]),
            "max_tokens": max_tokens,
            "stop": list(c["stop"]),
            "seed": int(m["seed"]),
        }


    def _ts(self) -> str:
        if not self.cfg["ui"]["timestamps"]:
            return ""
        return f" · {datetime.now().strftime('%H:%M:%S')}"

    def print_user(self, text: str) -> None:
        ui = self.cfg["ui"]
        th = self.th
        self.console.print(Panel(
            Text(text),
            title=(f"[{th['user']}]❯[/] "
                   f"[bold]{resc(ui['user_name'])}[/]{self._ts()}"),
            title_align="right",
            border_style=th["user"],
            box=self.box, padding=(0, 1)))

    def print_reply(self, text: str, tokens: int, seconds: float,
                    cancelled: bool = False) -> None:
        ui = self.cfg["ui"]
        th = self.th
        body: Any = (Markdown(text, code_theme=ui["code_theme"])
                     if ui["markdown"] else Text(text))
        subtitle = None
        if ui["show_speed"] and seconds > 0 and tokens > 0:
            subtitle = (f"[{self.th['dim']}]"
                        f"⚡ {tokens} tok · {tokens / seconds:.1f} tok/s · "
                        f"{seconds:.1f}s[/]"
                        + (" · [bold red]cancelled[/]" if cancelled else ""))
        self.console.print(Panel(
            body,
            title=(f"[{th['bot']}]✦[/] "
                   f"[bold]{resc(ui['bot_name'])}[/]{self._ts()}"),
            title_align="left",
            subtitle=subtitle, subtitle_align="right",
            border_style=th["bot"], box=self.box, padding=(0, 1)))
        if ui["sound"] and not cancelled:
            sys.stdout.write("\a")
            sys.stdout.flush()

    def note(self, text: str, kind: str = "dim") -> None:
        self.console.print(Text(text, style=self.th[kind]))

    def error(self, text: str) -> None:
        self.console.print(Panel(Text(text), title="[bold]✖ error[/]",
                                 border_style=self.th["error"], box=self.box))

    def print_banner(self) -> None:
        show_banner(self.console, self.cfg, self.backend.info,
                    demo=isinstance(self.backend, MockBackend))

    def _stream_view(self, text: str) -> Any:
        th = self.th
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        spin = frames[int(time.time() * 12) % len(frames)]
        return Group(Text.assemble(
            (f"{spin} ", f"bold {th['bot']}"),
            (f"{self.cfg['ui']['bot_name']} is writing…",
             f"italic {th['dim']}")),
            Text(text + "▌"))

    def _thinking_view(self, seconds: float) -> Any:
        th = self.th
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        spin = frames[int(time.time() * 12) % len(frames)]
        return Group(
            Text.assemble(
                (f"{spin} ", f"bold {th['bot']}"),
                (f"{self.cfg['ui']['bot_name']} is thinking",
                 f"italic {th['dim']}"),
                (f"  ·  {seconds:.0f}s", f"bold {th['primary']}")),
            Text("reading your message and preparing the first token — "
                 "on CPU this can take a little while",
                 style=th["dim"]),
            Text("Ctrl+C cancels", style=th["dim"]))

    def _wait_first_token(self, gen: Iterator[str]) -> Any:
        holder: Dict[str, Any] = {}

        def _pull() -> None:
            try:
                holder["first"] = next(gen, None)
            except BaseException as exc:
                holder["error"] = exc

        worker = threading.Thread(target=_pull, daemon=True)
        worker.start()
        if not self.console.is_terminal:
            worker.join()
            if "error" in holder:
                raise holder["error"]
            return holder.get("first")
        start = time.time()
        try:
            with Live(self._thinking_view(0.0), console=self.console,
                      refresh_per_second=12, transient=True) as live:
                while worker.is_alive():
                    live.update(self._thinking_view(time.time() - start))
                    time.sleep(0.08)
        except KeyboardInterrupt:
            raise
        except Exception:
            while worker.is_alive():
                time.sleep(0.1)
        worker.join()
        if "error" in holder:
            raise holder["error"]
        return holder.get("first")

    def generate(self) -> None:
        if not self.convo.messages or self.convo.messages[-1]["role"] != "user":
            self.note("nothing to generate — ask something first", "warn")
            return
        params = self.sampling_params()
        history = self.fit_context(self.convo.messages, params["max_tokens"])
        messages = ([{"role": "system", "content": self.build_system()}]
                    + history)
        text = ""
        cancelled = False
        start = time.time()
        interactive = self.console.is_terminal
        stream_on = bool(self.cfg["chat"]["stream"])

        try:
            gen = self.backend.stream(messages, params)
            try:
                if stream_on and interactive:
                    first = self._wait_first_token(gen)
                    text = first or ""
                    with Live(self._stream_view(text), console=self.console,
                              refresh_per_second=24, transient=True,
                              vertical_overflow="visible") as live:
                        for piece in gen:
                            text += piece
                            live.update(self._stream_view(text))
                else:
                    if interactive:
                        with self._status():
                            for piece in gen:
                                text += piece
                    else:
                        for piece in gen:
                            text += piece
            except KeyboardInterrupt:
                cancelled = True
                with contextlib.suppress(Exception):
                    gen.close()
        except KeyboardInterrupt:
            cancelled = True
        except Exception as exc:
            log_error("generation failed")
            self.error(f"generation failed: {exc}")
            return

        seconds = time.time() - start
        text = text.strip()
        if not text:
            self.note("∅ model returned an empty response", "warn")
            return
        usage = getattr(self.backend, "last_usage", None) or {}
        tokens = int(usage.get("completion_tokens") or self.count(text))
        self.gen_count += 1
        self.gen_tokens += tokens
        self.gen_seconds += seconds
        self.convo.add("assistant", text)
        self.print_reply(text, tokens, seconds, cancelled=cancelled)
        self.autosave()

    @contextlib.contextmanager
    def _status(self) -> Iterator[None]:
        th = self.th
        try:
            with self.console.status(
                    Text(f"✦ {self.cfg['ui']['bot_name']} is thinking…",
                         style=f"bold {th['bot']}"),
                    spinner=self.cfg["ui"]["spinner"]):
                yield
        except Exception:
            with self.console.status("thinking…"):
                yield


    def session_path(self, name: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-"
                       for ch in name).strip("-") or "session"
        return SESSIONS_DIR / f"{safe}.json"

    def autosave(self) -> None:
        try:
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            data = self.convo.to_dict()
            data["title"] = next((m["content"][:60] for m in
                                  self.convo.messages if m["role"] == "user"),
                                 "untitled")
            data["model"] = self.backend.info.get("name", "")
            self.session_path(AUTOSAVE_NAME).write_text(
                json.dumps(data, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            pass

    def save_session(self, name: str) -> Path:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        data = self.convo.to_dict()
        data["title"] = next((m["content"][:60] for m in
                              self.convo.messages if m["role"] == "user"),
                             "untitled")
        data["model"] = self.backend.info.get("name", "")
        path = self.session_path(name)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path

    def load_session(self, name: str) -> bool:
        path = self.session_path(name)
        if not path.exists():
            self.error(f"session not found: {name} — /sessions to list")
            return False
        try:
            self.convo.load_dict(json.loads(path.read_text(encoding="utf-8")))
            self.note(f"↺ loaded session '{name}' "
                      f"({len(self.convo.messages)} messages)", "good")
            return True
        except Exception as exc:
            self.error(f"could not load session: {exc}")
            return False

    def export_markdown(self, path: Path) -> None:
        ui = self.cfg["ui"]
        lines = [f"# Chat export — {ui['bot_name']}",
                 f"_Exported {datetime.now().strftime('%Y-%m-%d %H:%M')}_", ""]
        for m in self.convo.messages:
            who = ui["user_name"] if m["role"] == "user" else ui["bot_name"]
            lines.append(f"### {who}\n\n{m['content']}\n")
        path.write_text("\n".join(lines), encoding="utf-8")
        self.note(f"⇩ exported {len(self.convo.messages)} messages → {path}",
                  "good")


    def switch_model(self) -> None:
        if self.model_chooser is None or self.backend_builder is None:
            self.note("model switching isn't available in this mode", "warn")
            return
        path = self.model_chooser()
        if path is None:
            self.note("switch cancelled", "dim")
            return
        try:
            new_backend = self.backend_builder(path)
        except SystemExit:
            return
        except Exception as exc:
            log_error("model switch failed")
            self.error(f"could not load that model: {exc}")
            return
        with contextlib.suppress(Exception):
            self.backend.close()
        self.backend = new_backend
        self.convo.clear()
        self._tok_cache.clear()
        save_last_model(Path(path))
        info = self.backend.info
        self.note(f"✓ switched to {info['name']} — context cleared", "good")


    def handle_command(self, line: str) -> Optional[str]:
        parts = line.strip().split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            return "quit"
        if cmd in ("/help", "/?"):
            self.cmd_help()
        elif cmd == "/about":
            self.cmd_about()
        elif cmd in ("/settings", "/config"):
            self.cmd_settings()
        elif cmd == "/set":
            self.cmd_set(arg)
        elif cmd == "/themes":
            self.cmd_themes()
        elif cmd == "/theme":
            self.cmd_theme(arg)
        elif cmd == "/preset":
            self.cmd_preset(arg)
        elif cmd == "/system":
            self.cmd_system(arg)
        elif cmd == "/grounded":
            self.cmd_grounded(arg)
        elif cmd == "/mode":
            self.cmd_mode(arg)
        elif cmd == "/persona":
            self.cmd_persona()
        elif cmd == "/remember":
            self.cmd_remember(arg)
        elif cmd in ("/memories", "/memory"):
            self.cmd_memories()
        elif cmd == "/forget":
            self.cmd_forget(arg)
        elif cmd == "/temp":
            self._quick_set("sampling.temperature", arg, "temperature")
        elif cmd == "/maxtokens":
            self._quick_set("chat.max_tokens", arg, "max tokens")
        elif cmd == "/markdown":
            if arg.lower() in ("on", "off"):
                self.cfg["ui"]["markdown"] = arg.lower() == "on"
            else:
                self.cfg["ui"]["markdown"] = not self.cfg["ui"]["markdown"]
            save_config(self.cfg)
            self.note(f"✓ markdown → "
                      f"{'on' if self.cfg['ui']['markdown'] else 'off'}",
                      "good")
        elif cmd == "/models":
            self.cmd_models()
        elif cmd == "/recommend":
            self.cmd_recommend()
        elif cmd == "/switch":
            self.switch_model()
        elif cmd == "/save":
            name = arg or datetime.now().strftime("chat-%Y%m%d-%H%M%S")
            self.note(f"⇧ session saved → {self.save_session(name)}", "good")
        elif cmd == "/load":
            if arg:
                self.load_session(arg)
            else:
                self.cmd_sessions()
        elif cmd == "/sessions":
            self.cmd_sessions()
        elif cmd == "/export":
            dest = Path(arg) if arg else Path(
                f"chat-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md")
            try:
                self.export_markdown(dest)
            except OSError as exc:
                self.error(f"export failed: {exc}")
        elif cmd in ("/clear", "/new", "/reset"):
            self.convo.clear()
            self._tok_cache.clear()
            self.note("✦ context cleared — fresh start "
                      "(long-term memories kept)", "good")
        elif cmd == "/undo":
            removed = self.convo.undo()
            self.note(f"↩ removed {len(removed)} message(s)"
                      if removed else "nothing to undo",
                      "good" if removed else "warn")
        elif cmd == "/regen":
            if self.convo.pop_last_assistant() is None:
                self.note("nothing to regenerate", "warn")
            else:
                self.note("↻ regenerating…", "dim")
                self.generate()
        elif cmd == "/tokens":
            self.cmd_tokens()
        elif cmd == "/stats":
            self.cmd_stats()
        elif cmd == "/model":
            self.cmd_model()
        else:
            self.note(f"unknown command: {cmd} — try /help", "warn")
        return None

    def _quick_set(self, path: str, arg: str, label: str) -> None:
        if not arg:
            self.note(f"{label} is {cfg_get(self.cfg, path)}", "dim")
            return
        try:
            val = cfg_set(self.cfg, path, arg)
            save_config(self.cfg)
            self.note(f"✓ {label} → {val}", "good")
        except (KeyError, ValueError) as exc:
            self.error(f"could not set {label}: {exc}")

    def cmd_help(self) -> None:
        th = self.th
        t = Table(title="✦ command reference", border_style=th["primary"],
                  box=self.box, show_edge=False)
        t.add_column("command", style=f"bold {th['accent']}",
                     no_wrap=True, min_width=34)
        t.add_column("what it does", style=th["dim"])
        sections = [
            ("conversation", [
                ("/clear · /undo · /regen", "clear context · undo last turn · regenerate reply"),
                ("/tokens", "live context usage meter"),
                ("/quit", "exit (Ctrl-D also works)"),
            ]),
            ("models", [
                ("/models · /switch", "list models in models/ · switch model live"),
                ("/recommend", "which model fits this pc best"),
                ("/model", "details of the loaded model"),
            ]),
            ("behaviour", [
                ("/mode [flash|normal|reasoning]", "speed vs depth — fastest to deepest thinking"),
                ("/preset <name>", "system prompt preset (balanced, grounded, creative, coder, concise)"),
                ("/system [text]", "show or override the system prompt"),
                ("/persona", "show your personalization (edit personalization.txt)"),
                ("/grounded [on|off|strict]", "anti-hallucination grounding"),
                ("/temp <0-2> · /maxtokens <n>", "quick sampling tweaks"),
                ("/markdown [on|off]", "toggle markdown rendering"),
            ]),
            ("settings & appearance", [
                ("/settings · /set <key> [value]", "browse / read / change any setting (live)"),
                ("/themes · /theme <name>", "preview / switch color theme"),
            ]),
            ("memory", [
                ("/remember <text>", "save a fact Wander keeps forever"),
                ("/memories · /forget <#>", "list memories · remove one"),
            ]),
            ("sessions", [
                ("/save [name] · /load <name>", "save / load a session"),
                ("/sessions · /export [file.md]", "list sessions · export transcript"),
                ("/stats", "session statistics"),
            ]),
            ("information", [
                ("/about", "about wander"),
                ("/help", "this reference"),
            ]),
        ]
        first = True
        for title, rows in sections:
            if not first:
                t.add_section()
            first = False
            t.add_row(Text(title.upper(), style=f"bold {th['primary']}"),
                      Text(""))
            for row in rows:
                t.add_row(*row)
        self.console.print(t)
        self.note("tip: Alt+Enter inserts a new line while typing · "
                  "diagnostics: data/wander.log", "dim")

    def cmd_about(self) -> None:
        body = Table(box=None, show_header=False, pad_edge=False)
        body.add_column(no_wrap=True, style=f"bold {self.th['accent']}")
        body.add_column(style=self.th["dim"])
        body.add_row("portability", "self-contained folder, pendrive-ready")
        body.add_row("privacy", "100% offline — nothing leaves your machine")
        self.console.print(Panel(Group(
            Text.assemble(("✦ ", f"bold {self.th['primary']}"),
                          ("WANDER", f"bold {self.th['primary']}"),
                          ("   offline AI, anywhere", self.th["dim"])),
            Text(""),
            body,
        ), border_style=self.th["primary"], box=self.box))

    def cmd_settings(self) -> None:
        t = Table(title="✦ settings — change with /set key value",
                  border_style=self.th["primary"], box=self.box,
                  show_edge=False)
        t.add_column("key", style=self.th["accent"], no_wrap=True)
        t.add_column("value", style="bold")
        t.add_column("scope", style=self.th["dim"])
        for key in flatten_keys(DEFAULTS):
            try:
                val = cfg_get(self.cfg, key)
            except KeyError:
                continue
            shown = str(val)
            if len(shown) > 40:
                shown = shown[:39] + "…"
            t.add_row(key, shown,
                      "restart" if key in RESTART_KEYS else "live")
        self.console.print(t)

    def cmd_set(self, arg: str) -> None:
        if not arg:
            self.cmd_settings()
            return
        bits = arg.split(None, 1)
        key = bits[0]
        valid = set(flatten_keys(DEFAULTS))
        if key not in valid:
            close = [k for k in sorted(valid)
                     if key.split(".")[0] == k.split(".")[0]]
            self.error(f"unknown setting '{key}'\nvalid keys: "
                       + ", ".join(close[:12]))
            return
        if len(bits) == 1:
            self.note(f"{key} = {cfg_get(self.cfg, key)!r}", "dim")
            return
        try:
            val = cfg_set(self.cfg, key, bits[1])
        except ValueError as exc:
            self.error(str(exc))
            return
        save_config(self.cfg)
        extra = " — takes effect on next start" if key in RESTART_KEYS else ""
        self.note(f"✓ {key} → {val!r}{extra}", "good")

    def cmd_themes(self) -> None:
        t = Table(title="✦ themes — switch with /theme <name>",
                  border_style=self.th["primary"], box=self.box,
                  show_edge=False)
        t.add_column("name", style="bold")
        t.add_column("swatch")
        current = self.cfg["ui"]["theme"]
        for name, th in THEMES.items():
            sw = Text()
            for c in th["gradient"] + [th["user"], th["bot"], th["accent"]]:
                sw.append("██", style=c)
            t.add_row(name + (" ✓" if name == current else ""), sw)
        self.console.print(t)

    def cmd_theme(self, arg: str) -> None:
        if not arg:
            self.cmd_themes()
            return
        if arg not in THEMES:
            self.error(f"unknown theme '{arg}' — /themes to list")
            return
        self.cfg["ui"]["theme"] = arg
        save_config(self.cfg)
        th = self.th
        self.console.print(Panel(Group(
            Text.assemble(("✦ theme switched to ", th["dim"]),
                          (arg, f"bold {th['primary']}")),
            Text("the quick brown fox jumps over the lazy developer")),
            border_style=th["primary"], box=self.box))

    def cmd_preset(self, arg: str) -> None:
        if not arg:
            t = Table(title="✦ system prompt presets",
                      border_style=self.th["primary"], box=self.box,
                      show_edge=False)
            t.add_column("preset", style=f"bold {self.th['accent']}")
            t.add_column("description", style=self.th["dim"])
            for name in PRESETS:
                t.add_row(name, PRESETS[name][:80] + "…")
            self.console.print(t)
            self.note(f"current: {self.cfg['chat']['system_preset']} — "
                      "/preset <name> to switch", "dim")
            return
        if arg not in PRESETS:
            self.error(f"unknown preset '{arg}' — options: "
                       + ", ".join(PRESETS))
            return
        self.cfg["chat"]["system_preset"] = arg
        self.cfg["chat"]["system_prompt"] = ""
        save_config(self.cfg)
        self.note(f"✓ system preset → {arg}", "good")

    def cmd_system(self, arg: str) -> None:
        if arg.lower() == "off":
            self.cfg["chat"]["system_prompt"] = ""
            save_config(self.cfg)
            self.note("✓ custom system prompt cleared (using preset)", "good")
            return
        if arg:
            self.cfg["chat"]["system_prompt"] = arg
            save_config(self.cfg)
            self.note("✓ custom system prompt set", "good")
            return
        self.console.print(Panel(Text(self.build_system()),
                                 title="active system prompt",
                                 border_style=self.th["accent"], box=self.box))

    def cmd_mode(self, arg: str) -> None:
        cur = str(self.cfg["chat"].get("mode", "normal")).lower()
        if not arg:
            t = Table(title="✦ generation modes — /mode <name>",
                      border_style=self.th["primary"], box=self.box,
                      show_edge=False)
            t.add_column("mode", style=f"bold {self.th['accent']}")
            t.add_column("what it does", style=self.th["dim"])
            for name, profile in MODES.items():
                label = name + (" ✓" if name == cur else "")
                t.add_row(label, str(profile.get("blurb", "")))
            self.console.print(t)
            return
        arg = arg.lower()
        if arg not in MODES:
            self.error(f"unknown mode '{arg}' — options: "
                       + ", ".join(MODES))
            return
        self.cfg["chat"]["mode"] = arg
        save_config(self.cfg)
        self.note(f"✓ mode → {arg} ({MODES[arg].get('blurb', '')})", "good")

    def cmd_grounded(self, arg: str) -> None:
        g = self.cfg["grounding"]
        arg = arg.lower()
        if arg in ("on", "true", "1"):
            g["enabled"], g["strict"] = True, False
        elif arg == "strict":
            g["enabled"], g["strict"] = True, True
        elif arg in ("off", "false", "0"):
            g["enabled"], g["strict"] = False, False
        elif arg:
            self.error("usage: /grounded [on|off|strict]")
            return
        save_config(self.cfg)
        state = "strict" if g["strict"] else "on" if g["enabled"] else "off"
        self.note(f"✓ grounding → {state}", "good")

    def cmd_persona(self) -> None:
        if not self.cfg["chat"].get("personalization", True):
            self.note("personalization is off — "
                      "/set chat.personalization true", "warn")
            return
        text = load_personalization()
        if not text:
            self.note(f"no active personalization yet — edit "
                      f"{PERSONA_FILE.name} (lines starting with # "
                      "are ignored); changes apply instantly", "dim")
            return
        self.console.print(Panel(
            Text(text),
            title="✦ active personalization",
            subtitle=f"[{self.th['dim']}]{resc(str(PERSONA_FILE))}[/]",
            subtitle_align="right",
            border_style=self.th["accent"], box=self.box))
        self.note("edit the file anytime — changes apply instantly, "
                  "no restart needed", "dim")

    def cmd_models(self) -> None:
        models = discover_models()
        if not models:
            self.note(f"no .gguf files found in {MODELS_DIR}", "warn")
            return
        last = load_last_model()
        _, best, _ = evaluate_models(models)
        best_path = best["model"].path if best else None
        t = Table(title=f"✦ models in {MODELS_DIR}",
                  border_style=self.th["primary"], box=self.box,
                  show_edge=False)
        t.add_column("#", justify="right", style=self.th["accent"])
        t.add_column("model", style="bold")
        t.add_column("size", justify="right")
        t.add_column("quant")
        t.add_column("arch", style=self.th["dim"])
        t.add_column("ctx", justify="right", style=self.th["dim"])
        t.add_column("fit", style=self.th["dim"])
        for i, m in enumerate(models, 1):
            mark = " (active)" if (
                not isinstance(self.backend, MockBackend)
                and Path(self.backend.path).resolve() == m.path.resolve()
            ) else (" (last)" if last and last.resolve() == m.path.resolve()
                    else "")
            star = " ★" if best_path and m.path == best_path else ""
            warn = "" if m.supported or not m.arch else " ⚠"
            fit = self._fit_label(m)
            t.add_row(str(i), m.display + mark + star, human_size(m.size),
                      m.quant, (m.arch_friendly or m.arch or "?") + warn,
                      f"{m.ctx:,}" if m.ctx else "?", fit)
        self.console.print(t)
        self.note("/switch to change · /recommend for the best fit", "dim")

    def _fit_label(self, m: ModelInfo) -> str:
        results, _, _ = evaluate_models([m])
        return results[0]["fit"] if results else "?"

    def cmd_recommend(self) -> None:
        models = discover_models()
        if not models:
            self.note(f"no .gguf files found in {MODELS_DIR}", "warn")
            return
        results, best, info = evaluate_models(models)
        th = self.th
        t = Table(title="✦ which model fits this pc",
                  border_style=th["primary"], box=self.box, show_edge=False)
        t.add_column("model", style="bold")
        t.add_column("params", justify="right", style=th["dim"])
        t.add_column("needs", justify="right")
        t.add_column("fit")
        t.add_column("score", justify="right", style=th["dim"])
        fit_style = {"comfortable": th["good"], "ok": th["good"],
                     "tight": th["warn"], "too big": th["error"],
                     "?": th["dim"]}
        for r in sorted(results, key=lambda r: -r["score"]):
            m = r["model"]
            star = " ★" if best and m.path == best["model"].path else ""
            params = (f"{m.params / 1e9:.1f}B"
                      if m.params else "?")
            t.add_row(m.display + star, params, human_size(r["need"]),
                      Text(r["fit"], style=fit_style.get(r["fit"], "")),
                      f"{r['score']:.0f}")
        self.console.print(t)

        ram = info["ram"]
        line = Text.assemble(
            ("this pc: ", th["dim"]),
            (f"{ram / 2 ** 30:.1f} GB RAM" if ram else "RAM unknown",
             "bold"),
            (f" · {info['cores']} cores", th["dim"]),
            (f" · gpu: {info['gpu']}", th["dim"]),
        )
        self.console.print(line)
        if best:
            m = best["model"]
            kind = "chat/instruct-tuned" if m.instruct else "base"
            self.console.print(Text.assemble(
                ("best pick: ", th["dim"]),
                (f"{m.display} ", f"bold {th['good']}"),
                (f"({kind}, {best['fit']})", th["dim"]),
            ))
            if not m.instruct:
                self.note("note: an instruct-tuned model usually chats "
                          "better than a base model", "warn")
        else:
            self.note("no model here fits this pc comfortably — try a "
                      "smaller one", "warn")

    def cmd_sessions(self) -> None:
        t = Table(title=f"✦ sessions in {SESSIONS_DIR}",
                  border_style=self.th["primary"], box=self.box,
                  show_edge=False)
        t.add_column("name", style=f"bold {self.th['accent']}")
        t.add_column("title", style=self.th["dim"])
        t.add_column("msgs", justify="right")
        t.add_column("saved", style=self.th["dim"])
        found = False
        if SESSIONS_DIR.exists():
            for f in sorted(SESSIONS_DIR.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                found = True
                t.add_row(f.stem, str(data.get("title", ""))[:48],
                          str(len(data.get("messages", []))),
                          str(data.get("saved_at", "?")))
        if not found:
            self.note("no saved sessions yet — /save <name>", "dim")
            return
        self.console.print(t)

    def cmd_tokens(self) -> None:
        used = self._context_tokens()
        ctx = self.backend.n_ctx or 1
        ratio = min(1.0, used / ctx)
        color = ("#4ade80" if ratio < 0.6 else
                 "#fbbf24" if ratio < 0.85 else "#f87171")
        self.console.print(Group(
            Text(f"context usage: {used:,} / {ctx:,} tokens "
                 f"({int(ratio * 100)}%)", style=self.th["dim"]),
            ProgressBar(total=ctx, completed=min(used, ctx), width=40,
                        complete_style=color, finished_style=color),
        ))

    def cmd_stats(self) -> None:
        t = Table(title="✦ session stats", border_style=self.th["primary"],
                  box=self.box, show_edge=False)
        t.add_column("metric", style=self.th["dim"])
        t.add_column("value", style="bold")
        avg = (self.gen_tokens / self.gen_seconds
               if self.gen_seconds > 0 else 0.0)
        t.add_row("turns", str(self.convo.turns))
        t.add_row("messages", str(len(self.convo.messages)))
        t.add_row("generations", str(self.gen_count))
        t.add_row("tokens generated", f"{self.gen_tokens:,}")
        t.add_row("avg speed", f"{avg:.1f} tok/s")
        t.add_row("session time", hms(time.time() - self.started))
        t.add_row("context", f"{self._context_tokens():,} / "
                             f"{self.backend.n_ctx:,}")
        self.console.print(t)

    def cmd_model(self) -> None:
        t = Table(title="✦ model", border_style=self.th["primary"],
                  box=self.box, show_edge=False)
        t.add_column("field", style=self.th["dim"])
        t.add_column("value", style="bold")
        for k, v in self.backend.info.items():
            t.add_row(k, str(v))
        self.console.print(t)


    def run(self) -> None:
        if not self.banner_shown:
            self.print_banner()
        if self.persona_note:
            self.note(self.persona_note, "dim")
        while True:
            try:
                raw = self.read_input()
            except KeyboardInterrupt:
                self.note("\n(interrupted — press Ctrl-D or type /quit "
                          "to exit)", "warn")
                continue
            except EOFError:
                break
            line = raw.strip()
            if not line:
                continue
            if line.startswith("/"):
                if self.handle_command(line) == "quit":
                    break
                continue
            self._erase_echo(raw.rstrip("\n"))
            self.print_user(line)
            self.convo.add("user", line)
            self.generate()
        self.autosave()
        self.console.print()
        self.console.print(Align.center(
            gradient_rule(self.th["gradient"], 28)))
        self.console.print(Text("goodbye — session auto-saved "
                                "(resume with --resume)",
                                style=self.th["dim"]), justify="center")


def _engine_site_dirs() -> List[Path]:
    base = Path(sys.executable).resolve().parent
    candidates = [
        base / "Lib" / "site-packages",
        base.parent / "Lib" / "site-packages",
    ]
    lib = base.parent / "lib"
    if lib.exists():
        for pydir in sorted(lib.glob("python*")):
            candidates.append(pydir / "site-packages")
    return [c for c in candidates if c.is_dir()]


def _purge_bytecode() -> int:
    import shutil
    removed = 0
    for sp in _engine_site_dirs():
        for cache in sp.rglob("__pycache__"):
            with contextlib.suppress(Exception):
                shutil.rmtree(cache)
                removed += 1
    return removed


def _drop_engine_modules() -> None:
    for name in list(sys.modules):
        root = name.split(".")[0]
        if root in ("torch", "transformers", "huggingface_hub",
                    "tokenizers", "accelerate", "sentencepiece",
                    "safetensors"):
            del sys.modules[name]


def _try_import_engine() -> Optional[BaseException]:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return None
    except BaseException as exc:
        return exc


def _attempt_engine(want: str) -> Any:
    if want != "torch":
        try:
            import llama_cpp  # noqa: F401
            return "turbo", None
        except BaseException as exc:
            if want == "turbo":
                return None, exc
    err = _try_import_engine()
    return ("torch", None) if err is None else (None, err)


class EngineWarmup:
    def __init__(self, want: str) -> None:
        self.want = want
        self.done = False
        self.engine: Optional[str] = None
        self.error: Optional[BaseException] = None

    def _run(self) -> None:
        self.engine, self.error = _attempt_engine(self.want)
        self.done = True


def start_engine_warmup(want: str = "auto") -> EngineWarmup:
    w = EngineWarmup(want)
    threading.Thread(target=w._run, daemon=True).start()
    return w


def check_engine(console: Console,
                 warmup: Optional[EngineWarmup] = None) -> Optional[str]:
    th = THEMES["aurora"]
    want = warmup.want if warmup is not None else "auto"
    if warmup is not None:
        if not warmup.done:
            with console.status("warming up the engine…", spinner="dots12"):
                while not warmup.done:
                    time.sleep(0.05)
        engine, err = warmup.engine, warmup.error
    else:
        with console.status("warming up the engine…", spinner="dots12"):
            engine, err = _attempt_engine(want)
    if err is None:
        return engine

    _drop_engine_modules()
    removed = _purge_bytecode()
    if removed:
        console.print(Text(f"⚕ found a damaged bytecode cache — repaired "
                           f"{removed} folder(s), retrying…",
                           style=th["warn"]))
        with console.status("warming up the engine…", spinner="dots12"):
            engine, err = _attempt_engine(want)
        if err is None:
            return engine

    turbo_hint = ("")
    if want == "turbo":
        turbo_hint = ("Turbo engine not installed. Run INSTALL.bat, "
                      "option 2 — or set model.engine = \"auto\" to use "
                      "the built-in engine.\n\n")
    console.print(Panel(Text.assemble(
        ("The engine could not start.\n\n", "bold"),
        (f"reason: {err}\n\n", th["dim"]),
        (turbo_hint, th["warn"]),
        ("Run the installer to set up or repair the engine "
         "(INSTALL.bat on Windows, ./install.sh on Linux).", "bold green"),
    ), title="[bold red]✖ engine missing[/]", border_style="red",
        box=rbox.ROUNDED))
    return None


def build_backend(cfg: Dict[str, Any], path: Path,
                  console: Console,
                  meta: Optional[ModelInfo] = None,
                  engine: str = "torch") -> Any:
    th = THEMES.get(cfg["ui"]["theme"], THEMES["aurora"])
    if meta is None:
        meta = ModelInfo(path).load_meta()
    if not meta.readable:
        console.print(Panel(Text.assemble(
            (f"{path.name} ", "bold"),
            ("doesn't look like a readable GGUF file "
             "(corrupt or incomplete download?).", "")),
            title="[bold red]✖ bad model file[/]", border_style="red",
            box=rbox.ROUNDED))
        raise SystemExit(2)
    if meta.arch and not meta.supported:
        console.print(Panel(Text.assemble(
            ("architecture ", ""), (meta.arch, "bold"),
            (" may not be supported. Trying anyway.", "")),
            title="[bold yellow]⚠ heads up[/]", border_style="yellow",
            box=rbox.ROUNDED))
    try:
        with console.status(Text(f"loading {meta.display}…",
                                 style=f"bold {th['bot']}"),
                            spinner=cfg["ui"]["spinner"]):
            if engine == "turbo":
                backend: Any = TurboBackend(cfg, path, meta)
            else:
                backend = TransformersBackend(cfg, path, meta)
        save_last_model(path)
        return backend
    except SystemExit:
        raise
    except Exception as exc:
        console.print(Panel(Text.assemble(
            (f"could not load {path.name}:\n{exc}\n\n", ""),
            ("common fixes:\n", "bold"),
            ("• not enough RAM — pick a smaller model (0.5B–3B) or a "
             "smaller quant\n", ""),
            ("• set model.precision = \"fp16\" in /settings to halve RAM\n", ""),
            ("• the file must be complete (partial downloads fail)\n", ""),
        ), title="[bold red]✖ load failed[/]", border_style="red",
            box=rbox.ROUNDED))
        raise SystemExit(2)


def select_model_path(cfg: Dict[str, Any], console: Console,
                      args: argparse.Namespace,
                      models: List[ModelInfo]) -> Optional[Path]:
    if args.model:

        for m in models:
            if (args.model in (str(m.path), m.path.name)
                    or args.model.lower() in m.path.name.lower()):
                return m.path
        if args.model.isdigit() and 1 <= int(args.model) <= len(models):
            return models[int(args.model) - 1].path
        p = Path(args.model)
        if p.exists():
            return p
        console.print(Panel(Text(f"model not found: {args.model}\n"
                                 f"searched {MODELS_DIR}"),
                            title="[bold red]✖ model[/]", border_style="red",
                            box=rbox.ROUNDED))
        return None

    if not models:
        console.print(Panel(Text.assemble(
            ("No .gguf models found.\n\n", "bold"),
            ("Add .gguf files to:\n", ""),
            (f"    {MODELS_DIR}", "bold green"),
        ), title="[bold yellow]✦ models folder is empty[/]",
            border_style="yellow", box=rbox.ROUNDED))
        return None

    last = load_last_model()
    force_pick = args.pick or len(models) > 1 or last is None
    if not force_pick and last is not None:
        console.print(Text.assemble(
            ("✦ auto-loading last model: ", THEMES["aurora"]["dim"]),
            (last.stem, "bold"),
            ("   (--pick to choose)", THEMES["aurora"]["dim"])))
        return last
    return pick_model(console, cfg, models)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="wander",
        description="✦ Wander — portable offline terminal AI for your "
                    ".gguf models (no llama.cpp).")
    ap.add_argument("--model", help="model to load: filename, number, or "
                    "path (skips the picker)")
    ap.add_argument("--pick", action="store_true",
                    help="always show the model selection screen")
    ap.add_argument("--list-models", action="store_true",
                    help="list models found in models/ and exit")
    ap.add_argument("--threads", type=int, help="CPU threads")
    ap.add_argument("--engine", choices=["auto", "torch", "turbo"],
                    help="inference engine: turbo = llama.cpp if "
                         "installed, torch = pure PyTorch")
    ap.add_argument("--precision", choices=["auto", "fp32", "fp16", "bf16"],
                    help="weight precision (RAM vs quality)")
    ap.add_argument("--temp", type=float, help="sampling temperature")
    ap.add_argument("--top-p", type=float, help="nucleus sampling p")
    ap.add_argument("--max-tokens", type=int, help="max tokens per reply")
    ap.add_argument("--theme", choices=sorted(THEMES), help="UI theme")
    ap.add_argument("--preset", choices=sorted(PRESETS),
                    help="system prompt preset")
    ap.add_argument("--system", help="custom system prompt override")
    ap.add_argument("--session", help="load this saved session on start")
    ap.add_argument("--resume", action="store_true",
                    help="resume the auto-saved session")
    ap.add_argument("--demo", action="store_true",
                    help="run without a model to preview the UI")
    ap.add_argument("--no-markdown", action="store_true")
    ap.add_argument("-p", "--prompt",
                    help="one-shot: answer this prompt and exit")
    return ap.parse_args(argv)


def apply_cli_overrides(cfg: Dict[str, Any],
                        args: argparse.Namespace) -> None:
    if args.threads is not None:
        cfg["model"]["threads"] = args.threads
    if args.engine:
        cfg["model"]["engine"] = args.engine
    if args.precision:
        cfg["model"]["precision"] = args.precision
    if args.temp is not None:
        cfg["sampling"]["temperature"] = args.temp
    if args.top_p is not None:
        cfg["sampling"]["top_p"] = args.top_p
    if args.max_tokens:
        cfg["chat"]["max_tokens"] = args.max_tokens
    if args.theme:
        cfg["ui"]["theme"] = args.theme
    if args.preset:
        cfg["chat"]["system_preset"] = args.preset
        cfg["chat"]["system_prompt"] = ""
    if args.system:
        cfg["chat"]["system_prompt"] = args.system
    if args.no_markdown:
        cfg["ui"]["markdown"] = False


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    console = Console(highlight=False)
    boot_log("launch")

    cfg = load_config_file()
    apply_cli_overrides(cfg, args)
    sanitize_config(cfg)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    boot_log("config loaded")

    if args.list_models:
        models = discover_models()
        if not models:
            print(f"no .gguf files found in {MODELS_DIR}")
            return
        for i, m in enumerate(models, 1):
            print(f"{i}. {m.display} — {model_row_text(m, THEMES['aurora'])}"
                  f"\n   {m.path}")
        return

    if args.demo:
        backend: Any = MockBackend(cfg)
        show_banner(console, cfg, backend.info, demo=True)
    else:
        t_scan = time.time()
        models = discover_models()
        boot_log(f"models scanned: {len(models)} found in "
                 f"{time.time() - t_scan:.2f}s")
        path = select_model_path(cfg, console, args, models)
        if path is None:
            raise SystemExit(2)
        boot_log(f"model selected: {path.name}")
        meta = ModelInfo(path).load_meta()
        show_banner(console, cfg, {
            "name": meta.display,
            "context": meta.ctx or 4096,
        })
        engine_used = check_engine(console)
        if engine_used is None:
            raise SystemExit(2)
        boot_log(f"engine ready: {engine_used}")
        backend = build_backend(cfg, path, console, meta, engine_used)
        boot_log("model loaded — chat ready")

    app = ChatApp(cfg, backend)
    app.banner_shown = True

    persona_created = ensure_persona_template()
    if persona_created:
        app.persona_note = (f"✦ created {PERSONA_FILE.name} — edit it to "
                            "customize Wander")

    if not args.demo:
        app.backend_builder = lambda p: build_backend(
            cfg, Path(p), console, engine=engine_used)
        app.model_chooser = lambda: pick_model(console, cfg,
                                               discover_models())

    if args.resume:
        app.load_session(AUTOSAVE_NAME)
    elif args.session:
        app.load_session(args.session)
    elif not args.demo and cfg["chat"].get("auto_resume", True) \
            and app.session_path(AUTOSAVE_NAME).exists():
        app.load_session(AUTOSAVE_NAME)

    if args.prompt:
        app.convo.add("user", args.prompt)
        app.print_user(args.prompt)
        app.generate()
        return

    app.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as fatal_exc:
        crash_panel(Console(highlight=False), fatal_exc)
        sys.exit(1)

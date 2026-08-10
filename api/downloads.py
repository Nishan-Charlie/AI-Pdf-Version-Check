"""
Model Download Manager
──────────────────────
Fetching an encoder means pulling hundreds of megabytes from HuggingFace. Doing
that inside a comparison request gives the caller a single long silence, so it
is done as a tracked background job instead: start it, poll it, then compare.

Progress is measured in bytes rather than guessed. The repository's file sizes
are read from the Hub before anything is transferred, so the total is known
from the start and the bar does not jump as each new file begins.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from config import MODEL_REGISTRY

# Alternate runtimes and framework exports that sentence-transformers does not
# load. A BGE repository carries ONNX and OpenVINO copies of the same weights;
# fetching them would double or triple the download for no benefit.
IGNORE_PATTERNS = [
    "*.onnx", "onnx/*", "onnx_*/*",
    "openvino/*", "openvino_*/*",
    "*.h5", "*.tflite", "*.msgpack", "*.ot",
    "model.safetensors.index.json",
]

# States a job moves through, in order.
IDLE = "idle"
RESOLVING = "resolving"     # asking the Hub how big this is
DOWNLOADING = "downloading"
LOADING = "loading"         # weights on disk, building the model in memory
READY = "ready"
ERROR = "error"


@dataclass
class DownloadJob:
    """Progress of one model fetch."""

    model_id: str
    state: str = IDLE
    total_bytes: int = 0
    done_bytes: int = 0
    message: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    @property
    def percent(self) -> float:
        if self.state in (READY,):
            return 100.0
        if not self.total_bytes:
            return 0.0
        return min(99.9, self.done_bytes * 100.0 / self.total_bytes)

    def as_dict(self) -> dict:
        return {
            "model": self.model_id,
            "state": self.state,
            "percent": round(self.percent, 1),
            "done_bytes": self.done_bytes,
            "total_bytes": self.total_bytes,
            "message": self.message,
            "error": self.error,
            "elapsed_seconds": round((self.finished_at or time.time()) - self.started_at, 1),
        }


_jobs: dict[str, DownloadJob] = {}
_lock = threading.Lock()


def hf_repo_id(model_id: str) -> str:
    """
    The HuggingFace repository a model id refers to.

    Sentence-Transformers publishes its own models under an org, so a bare name
    like "all-MiniLM-L6-v2" lives at "sentence-transformers/all-MiniLM-L6-v2".
    """
    return model_id if "/" in model_id else f"sentence-transformers/{model_id}"


def get_job(model_id: str) -> Optional[DownloadJob]:
    with _lock:
        return _jobs.get(model_id)


def start(model_id: str) -> DownloadJob:
    """
    Begin fetching a model, or return the job already running for it.

    Safe to call repeatedly: a second call while a download is in flight joins
    the existing job rather than starting a competing one.
    """
    with _lock:
        existing = _jobs.get(model_id)
        if existing and existing.state not in (READY, ERROR):
            return existing

        job = DownloadJob(model_id=model_id, state=RESOLVING,
                          message="Checking what needs downloading…")
        _jobs[model_id] = job

    thread = threading.Thread(target=_run, args=(job,), daemon=True,
                              name=f"download:{model_id}")
    thread.start()
    return job


def _run(job: DownloadJob) -> None:
    """Fetch the weights, then load them, updating the job as it goes."""
    try:
        repo = hf_repo_id(job.model_id)
        job.total_bytes, patterns = _plan(repo, job.model_id)
        job.state = DOWNLOADING
        job.message = "Downloading weights…"

        _download(repo, job, patterns)

        job.state = LOADING
        job.message = "Loading the model…"
        job.done_bytes = job.total_bytes

        # Building the encoder here means the first comparison does not pay for
        # it, and the job only reports ready once the model can actually run.
        from comparison.engine import get_comparator
        get_comparator(job.model_id)

        job.state = READY
        job.message = "Ready"
    except Exception as exc:  # noqa: BLE001 — the message is the whole point
        job.state = ERROR
        job.error = str(exc)
        job.message = "Download failed"
    finally:
        job.finished_at = time.time()


def _plan(repo: str, model_id: str) -> tuple[int, list[str]]:
    """
    Work out what will be transferred and how much it is.

    Returns (total bytes, patterns to skip). The skip list is built per
    repository rather than fixed, because most publish the same weights twice —
    once as `model.safetensors` and once as `pytorch_model.bin`. Fetching both
    doubles the download for a file that will never be opened, so whichever
    format sentence-transformers will not choose is dropped.

    Falls back to the registry's rough figure if the Hub cannot be reached, so
    a progress bar still appears rather than nothing.
    """
    patterns = list(IGNORE_PATTERNS)

    try:
        from fnmatch import fnmatch

        from huggingface_hub import HfApi

        info = HfApi().model_info(repo, files_metadata=True)
        siblings = info.siblings or []
        names = {s.rfilename for s in siblings}

        # sentence-transformers loads safetensors when present.
        if any(n.endswith(".safetensors") for n in names):
            patterns += ["pytorch_model.bin", "*/pytorch_model.bin"]

        total = sum(
            s.size or 0
            for s in siblings
            if not any(fnmatch(s.rfilename, p) for p in patterns)
        )
        if total:
            return total, patterns
    except Exception:  # noqa: BLE001 — an estimate is not worth failing over
        pass

    for entry in MODEL_REGISTRY.values():
        if entry["id"] == model_id:
            return entry["size_mb"] * 1024 * 1024, patterns
    return 0, patterns


def _download(repo: str, job: DownloadJob, patterns: list[str]) -> None:
    """
    Pull the repository, reporting bytes as they arrive.

    Progress is read from the cache directory rather than from the transfer.
    huggingface_hub's `tqdm_class` hook counts *files* completed, not bytes, so
    a repository whose weight file is 400 MB reports nothing at all until that
    file lands — a bar that sits at zero and then jumps to done. Watching the
    directory grow works however the hub moves the bytes, including under the
    accelerated downloader.
    """
    from huggingface_hub import snapshot_download

    stop = threading.Event()
    watcher = threading.Thread(
        target=_watch_cache, args=(repo, job, stop), daemon=True,
        name=f"progress:{job.model_id}",
    )
    watcher.start()

    try:
        snapshot_download(
            repo_id=repo,
            ignore_patterns=patterns,
            max_workers=4,
        )
    finally:
        stop.set()
        watcher.join(timeout=2)


def _watch_cache(repo: str, job: DownloadJob, stop: threading.Event) -> None:
    """Poll the model's cache folder and report how much of it has arrived."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return

    folder = os.path.join(HF_HUB_CACHE, "models--" + repo.replace("/", "--"))

    while not stop.wait(0.4):
        size = _folder_size(folder)
        # Never report more than was promised: a cache layout that keeps both a
        # blob and a copy of it would otherwise overshoot the total.
        if job.total_bytes:
            size = min(size, job.total_bytes)
        if size > job.done_bytes:
            job.done_bytes = size


def _folder_size(path: str) -> int:
    """
    Bytes held under a directory, including partial downloads.

    Symlinks are measured as links rather than followed, so a cache that keeps
    the real file in blobs/ and links to it from snapshots/ counts it once.
    """
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name),
                                 follow_symlinks=False).st_size
            except OSError:
                continue  # vanished mid-walk; it will be counted next tick
    return total

"""
Utility functions for the OCR Batch Processor
"""
import os
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import config

logger = logging.getLogger(__name__)


def ensure_folder_exists(folder_path: str) -> bool:
    """
    Create folder if it doesn't exist

    Returns:
        True if folder exists or was created, False on error
    """
    try:
        os.makedirs(folder_path, exist_ok=True)
        return True
    except Exception:
        return False


def get_folder_stats(folder_path: str) -> dict:
    """
    Get statistics about PDFs in a folder

    Returns:
        Dict with file count, total size, etc.
    """
    if not os.path.exists(folder_path):
        return {"exists": False, "count": 0, "size_mb": 0}

    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
    total_size = sum(
        os.path.getsize(os.path.join(folder_path, f))
        for f in pdf_files
    )

    return {
        "exists": True,
        "count": len(pdf_files),
        "size_mb": round(total_size / (1024 * 1024), 2)
    }


def format_time(seconds: float) -> str:
    """Format seconds into human readable time"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def estimate_remaining_time(processed: int, total: int, elapsed_seconds: float) -> str:
    """Estimate remaining time based on current progress"""
    if processed == 0:
        return "Calculating..."

    avg_time_per_file = elapsed_seconds / processed
    remaining_files = total - processed
    remaining_seconds = avg_time_per_file * remaining_files

    return format_time(remaining_seconds)


class SessionState:
    """
    Manages session state for crash recovery
    Saves progress to a JSON file so processing can resume after crash
    """

    def __init__(self, state_file: str = None):
        self.state_file = state_file or config.STATE_FILE
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Load state from file or return empty state"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass

        return {
            "session_id": datetime.now().isoformat(),
            "started_at": None,
            "input_folder": None,
            "output_folder": None,
            "total_files": 0,
            "processed_files": [],
            "failed_files": [],
            "last_update": None
        }

    def save(self):
        """Save current state to file"""
        self.state["last_update"] = datetime.now().isoformat()
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception:
            pass

    def start_session(self, input_folder: str, output_folder: str, total_files: int):
        """Start a new processing session"""
        self.state = {
            "session_id": datetime.now().isoformat(),
            "started_at": datetime.now().isoformat(),
            "input_folder": input_folder,
            "output_folder": output_folder,
            "total_files": total_files,
            "processed_files": [],
            "failed_files": [],
            "last_update": None
        }
        self.save()

    def mark_processed(self, file_name: str, success: bool):
        """Mark a file as processed"""
        if success:
            if file_name not in self.state["processed_files"]:
                self.state["processed_files"].append(file_name)
        else:
            if file_name not in self.state["failed_files"]:
                self.state["failed_files"].append(file_name)
        self.save()

    def get_progress(self) -> tuple:
        """Get (processed_count, failed_count, total)"""
        return (
            len(self.state["processed_files"]),
            len(self.state["failed_files"]),
            self.state["total_files"]
        )

    def clear(self):
        """Clear the session state"""
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        self.state = self._load_state()


def get_free_disk_space_mb(path: str) -> float:
    """Get free disk space in MB for the drive containing the given path"""
    try:
        usage = shutil.disk_usage(path)
        return usage.free / (1024 * 1024)
    except Exception:
        return -1  # Unknown


def check_disk_space(output_folder: str, settings_file: Optional[str] = None) -> bool:
    """
    Check if output drive has enough free space.
    If below threshold, disables auto_start and returns False.

    Returns:
        True if enough space, False if disk full (auto_start disabled)
    """
    min_space_mb = getattr(config, 'MIN_DISK_SPACE_MB', 500)
    free_mb = get_free_disk_space_mb(output_folder)

    if free_mb < 0:
        return True  # Can't determine, proceed anyway

    if free_mb < min_space_mb:
        logger.error(
            f"DISK SPACE LOW: {free_mb:.0f}MB free on {os.path.splitdrive(output_folder)[0]} "
            f"(minimum: {min_space_mb}MB). Disabling auto_start."
        )
        # Disable auto_start in settings
        if settings_file is None:
            settings_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "auto_start.json"
            )
        try:
            settings = {}
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
            settings["auto_start"] = False
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            logger.error(f"Could not disable auto_start: {e}")
        return False
    return True


def find_error_folder_fallback(primary_error_folder: str) -> str:
    """
    Find a writable error folder. If the primary drive is full,
    try other available drives and create PDF_Work_Error there.

    Returns:
        Path to a writable error folder
    """
    # Try primary first
    try:
        os.makedirs(primary_error_folder, exist_ok=True)
        free_mb = get_free_disk_space_mb(primary_error_folder)
        if free_mb < 0 or free_mb >= 50:  # At least 50MB for error files
            return primary_error_folder
    except Exception:
        pass

    # Primary drive full or inaccessible - try other drives
    logger.warning(f"Primary error folder drive full, searching for fallback...")
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:\\"
        if not os.path.exists(drive):
            continue
        try:
            free_mb = get_free_disk_space_mb(drive)
            if free_mb >= 50:
                fallback = os.path.join(drive, "PDF_Work_Error")
                os.makedirs(fallback, exist_ok=True)
                logger.warning(f"Using fallback error folder: {fallback}")
                return fallback
        except Exception:
            continue

    # Last resort - return primary even if full
    logger.error("No drive with free space found for error folder!")
    return primary_error_folder


def get_system_info() -> dict:
    """Get basic system information"""
    import platform

    try:
        cpu_count = os.cpu_count() or 4
    except Exception:
        cpu_count = 4

    return {
        "platform": platform.system(),
        "cpu_count": cpu_count,
        "recommended_workers": min(cpu_count - 4, config.MAX_WORKERS)
    }


def _is_pid_running(pid: int) -> bool:
    """Check if a process with given PID is still running (Windows)"""
    if pid <= 0:
        return False
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


class LockManager:
    """
    PID-based file locking to prevent App and Worker from fighting.
    - Writes PID to lock file on acquire
    - Checks if PID is still alive on is_locked/acquire (no stale lock dead zones)
    - refresh() updates timestamp during long batches
    """
    def __init__(self, lock_name: str):
        self.lock_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), f"{lock_name}.lock"
        )

    def _read_pid(self) -> int:
        """Read PID from lock file, returns 0 if unreadable"""
        try:
            with open(self.lock_file, 'r') as f:
                return int(f.read().strip())
        except Exception:
            return 0

    def _is_stale(self) -> bool:
        """Check if lock file belongs to a dead process"""
        pid = self._read_pid()
        if pid == 0:
            return True  # Corrupted lock file
        return not _is_pid_running(pid)

    def acquire(self) -> bool:
        """Acquire lock. Clears stale locks from dead processes automatically."""
        if os.path.exists(self.lock_file):
            if self._is_stale():
                # Process that held the lock is dead - safe to take over
                try:
                    os.remove(self.lock_file)
                except Exception:
                    return False
            else:
                return False  # Lock held by a live process

        try:
            with open(self.lock_file, 'w') as f:
                f.write(str(os.getpid()))
            return True
        except Exception:
            return False

    def release(self):
        """Remove lock file (only if we own it)"""
        try:
            if os.path.exists(self.lock_file):
                pid = self._read_pid()
                if pid == os.getpid() or pid == 0:
                    os.remove(self.lock_file)
        except Exception:
            pass

    def refresh(self):
        """Update lock file timestamp to prevent false stale detection.
        Call this periodically during long-running batches."""
        try:
            if os.path.exists(self.lock_file):
                os.utime(self.lock_file, None)  # Touch the file
        except Exception:
            pass

    def is_locked(self) -> bool:
        """Check if lock is held by a live process"""
        if not os.path.exists(self.lock_file):
            return False
        return not self._is_stale()

    def get_owner_pid(self) -> int:
        """Get PID of the process holding the lock (0 if none)"""
        if not os.path.exists(self.lock_file):
            return 0
        return self._read_pid()

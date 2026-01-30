"""
Utility functions for the OCR Batch Processor
"""
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

import config


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

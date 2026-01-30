"""
Core OCR processing logic using PDF24 OCR CLI (pdf24-Ocr.exe)
"""
import subprocess
import os
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

import config

# Setup logging - console only (file logging handled by caller: worker.pyw or app.py)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Console handler only
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)


@dataclass
class ProcessingResult:
    """Result of a single file processing"""
    file_name: str
    success: bool
    message: str
    processing_time: float = 0.0
    error: Optional[str] = None


def validate_ocr_tool() -> bool:
    """Check if PDF24 OCR tool exists at configured path"""
    return os.path.exists(config.OCR_TOOL_PATH)


def kill_process_tree(pid: int) -> None:
    """Kill a process and all its children (Windows)"""
    try:
        # Use taskkill to kill process tree on Windows
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        logger.debug(f"Killed process tree for PID {pid}")
    except Exception as e:
        logger.warning(f"Could not kill process tree {pid}: {e}")


def kill_pdf24_processes() -> None:
    """Kill any hanging PDF24 OCR processes"""
    try:
        # Kill pdf24-Ocr.exe processes
        subprocess.run(
            ["taskkill", "/F", "/IM", "pdf24-Ocr.exe"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        logger.debug("Killed hanging PDF24 processes")
    except Exception as e:
        logger.warning(f"Could not kill PDF24 processes: {e}")


def build_ocr_command(input_path: str, output_path: str,
                      language: str = None, deskew: bool = True,
                      dpi: int = None) -> list:
    """
    Build the PDF24 OCR CLI command

    Args:
        input_path: Path to input PDF file
        output_path: Path for output PDF file
        language: OCR language(s), e.g., "eng+kan"
        deskew: Enable deskew correction
        dpi: DPI for processing

    Returns:
        List of command arguments
    """
    lang = language or config.OCR_LANGUAGES
    dpi_val = dpi or config.OCR_DPI

    # pdf24-Ocr.exe syntax:
    # pdf24-Ocr.exe -outputFile "output.pdf" -language eng+kan -dpi 300 -deskew "input.pdf"
    cmd = [
        config.OCR_TOOL_PATH,
        "-outputFile", output_path,
        "-language", lang,
        "-dpi", str(dpi_val),
    ]

    if deskew:
        cmd.append("-deskew")

    if config.OCR_REMOVE_BACKGROUND:
        cmd.append("-removeBackground")

    # Input file goes last
    cmd.append(input_path)

    return cmd


def process_single_pdf(file_path: str, output_folder: str,
                       language: str = None, deskew: bool = True,
                       clean: bool = True, delete_on_success: bool = True) -> ProcessingResult:
    """
    Process a single PDF file through OCR

    Args:
        file_path: Path to the input PDF
        output_folder: Folder to save OCR'd PDF
        language: OCR language(s)
        deskew: Enable deskew
        clean: Not used (kept for API compatibility)
        delete_on_success: Delete input file after successful processing

    Returns:
        ProcessingResult with status and details
    """
    file_name = os.path.basename(file_path)
    output_path = os.path.join(output_folder, file_name)
    start_time = datetime.now()

    logger.info(f"Starting OCR for: {file_name}")

    # Check if output already exists (skip if already processed)
    if os.path.exists(output_path):
        logger.info(f"Output already exists, skipping: {file_name}")
        return ProcessingResult(
            file_name=file_name,
            success=True,
            message="Already processed (output exists)"
        )

    # Build command
    cmd = build_ocr_command(file_path, output_path, language, deskew)

    logger.debug(f"Command: {' '.join(cmd)}")

    try:
        # Run PDF24 OCR CLI using Popen for better process control
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        try:
            stdout, stderr = process.communicate(timeout=600)  # 10 minute timeout
        except subprocess.TimeoutExpired:
            # Kill the process tree on timeout
            logger.warning(f"TIMEOUT: {file_name} - killing PDF24 process...")
            kill_process_tree(process.pid)
            process.kill()
            try:
                process.communicate(timeout=5)
            except:
                pass

            processing_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"TIMEOUT: {file_name} - process killed after {processing_time:.1f}s")
            return ProcessingResult(
                file_name=file_name,
                success=False,
                message="Timeout (>10 min)",
                error="Processing exceeded 10 minute limit - process killed",
                processing_time=processing_time
            )

        processing_time = (datetime.now() - start_time).total_seconds()

        # Log stdout/stderr for debugging
        if stdout:
            logger.debug(f"stdout: {stdout}")
        if stderr:
            logger.debug(f"stderr: {stderr}")

        # Check if output was created
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            # Success - optionally delete input
            if delete_on_success:
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted input file: {file_name}")
                except Exception as e:
                    logger.warning(f"Could not delete input file {file_name}: {e}")

            logger.info(f"SUCCESS: {file_name} ({processing_time:.1f}s)")
            return ProcessingResult(
                file_name=file_name,
                success=True,
                message=f"Processed successfully",
                processing_time=processing_time
            )
        else:
            # Output not created - kill any hanging PDF24 processes
            kill_pdf24_processes()
            error_msg = stderr or stdout or "Output file not created"
            logger.error(f"FAILED: {file_name} - {error_msg}")
            return ProcessingResult(
                file_name=file_name,
                success=False,
                message="OCR failed",
                error=error_msg,
                processing_time=processing_time
            )

    except Exception as e:
        # Kill any hanging PDF24 processes on crash
        kill_pdf24_processes()
        processing_time = (datetime.now() - start_time).total_seconds()
        logger.error(f"ERROR: {file_name} - {str(e)}")
        return ProcessingResult(
            file_name=file_name,
            success=False,
            message="Processing error",
            error=str(e),
            processing_time=processing_time
        )


def get_pending_files(input_folder: str, output_folder: str) -> list:
    """
    Get list of PDF files that haven't been processed yet

    Args:
        input_folder: Folder with input PDFs
        output_folder: Folder with processed PDFs

    Returns:
        List of file paths that need processing
    """
    if not os.path.exists(input_folder):
        return []

    # Get all PDFs in input folder
    input_files = [
        f for f in os.listdir(input_folder)
        if f.lower().endswith('.pdf')
    ]

    # Filter out already processed (check if output exists)
    pending = []
    for file_name in input_files:
        output_path = os.path.join(output_folder, file_name)
        if not os.path.exists(output_path):
            pending.append(os.path.join(input_folder, file_name))

    return sorted(pending)


def get_processed_count(output_folder: str) -> int:
    """Get count of already processed files in output folder"""
    if not os.path.exists(output_folder):
        return 0
    return len([f for f in os.listdir(output_folder) if f.lower().endswith('.pdf')])

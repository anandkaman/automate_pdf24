"""
Core OCR processing logic using PDF24 OCR CLI (pdf24-Ocr.exe)
"""
import subprocess
import os
import shutil
import logging
import time
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


def cleanup_partial_output(output_path: str) -> None:
    """Remove partial/corrupted output file if it exists"""
    try:
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size == 0:  # Empty file - definitely partial
                os.remove(output_path)
                logger.debug(f"Removed empty output file: {output_path}")
    except Exception as e:
        logger.warning(f"Could not clean up partial output: {e}")


def move_to_error_folder(file_path: str, error_folder: str) -> bool:
    """Move a failed file to the error folder"""
    try:
        if not os.path.exists(error_folder):
            os.makedirs(error_folder)

        file_name = os.path.basename(file_path)
        error_path = os.path.join(error_folder, file_name)

        # If file already exists in error folder, add timestamp
        if os.path.exists(error_path):
            name, ext = os.path.splitext(file_name)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            error_path = os.path.join(error_folder, f"{name}_{timestamp}{ext}")

        shutil.move(file_path, error_path)
        logger.info(f"Moved failed file to error folder: {file_name}")
        return True
    except Exception as e:
        logger.error(f"Could not move file to error folder: {e}")
        return False


def move_to_processing_folder(file_path: str, processing_folder: str, max_retries: int = 5) -> Optional[str]:
    """
    Move a file to the processing folder before OCR.
    Returns the new path in processing folder, or None if move failed.
    Includes retry logic for files that are temporarily locked (e.g., by Windows copy, antivirus).
    """
    if not os.path.exists(processing_folder):
        os.makedirs(processing_folder)

    file_name = os.path.basename(file_path)
    processing_path = os.path.join(processing_folder, file_name)

    # If file already exists in processing folder (crash recovery), use it
    if os.path.exists(processing_path):
        logger.info(f"File already in processing folder (crash recovery): {file_name}")
        return processing_path

    # Retry loop for temporarily locked files
    for attempt in range(max_retries):
        try:
            # If source doesn't exist anymore, check processing folder
            if not os.path.exists(file_path):
                if os.path.exists(processing_path):
                    return processing_path
                return None

            shutil.move(file_path, processing_path)
            logger.debug(f"Moved to processing: {file_name}")
            return processing_path

        except PermissionError as e:
            if attempt < max_retries - 1:
                # Wait longer each retry: 0.5s, 1s, 2s, 4s, 8s
                wait_time = 0.5 * (2 ** attempt)
                logger.debug(f"File locked, retry {attempt + 1}/{max_retries} in {wait_time}s: {file_name}")
                time.sleep(wait_time)
            else:
                logger.warning(f"File still locked after {max_retries} retries, skipping: {file_name}")
                return None
        except Exception as e:
            logger.error(f"Could not move file to processing folder: {e}")
            return None

    return None


def prepare_batch_for_processing(input_folder: str, output_folder: str, processing_folder: str,
                                  duplicate_folder: str = None, error_folder: str = None) -> list:
    """
    Move all pending files from Input to Processing folder SEQUENTIALLY.
    This prevents race conditions when parallel workers try to grab files.
    Also cleans up already-processed files from Processing folder.

    Returns:
        List of file paths in the Processing folder ready for OCR
    """
    ready_files = []

    # First, check Processing folder (crash recovery + cleanup)
    if os.path.exists(processing_folder):
        for f in os.listdir(processing_folder):
            if f.lower().endswith('.pdf'):
                processing_path = os.path.join(processing_folder, f)
                output_path = os.path.join(output_folder, f)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    # Already processed - clean up from Processing folder
                    try:
                        os.remove(processing_path)
                        logger.info(f"Cleanup: removed already-processed file from Processing: {f}")
                    except Exception as e:
                        logger.warning(f"Could not cleanup {f} from Processing: {e}")
                else:
                    # Not yet processed - add to ready list (crash recovery)
                    ready_files.append(processing_path)
                    logger.info(f"Crash recovery: {f} found in Processing folder")

    # Get pending files from Input folder
    pending = get_pending_files(input_folder, output_folder, duplicate_folder, error_folder)

    # Move files from Input to Processing sequentially
    for file_path in pending:
        file_name = os.path.basename(file_path)
        processing_path = os.path.join(processing_folder, file_name)

        # Skip if already in ready list (from crash recovery)
        if processing_path in ready_files:
            continue

        moved_path = move_to_processing_folder(file_path, processing_folder)
        if moved_path:
            ready_files.append(moved_path)

    return ready_files


def process_single_pdf(file_path: str, output_folder: str,
                       language: str = None, deskew: bool = True,
                       clean: bool = True, delete_on_success: bool = True,
                       max_retries: int = 2, error_folder: str = None,
                       processing_folder: str = None) -> ProcessingResult:
    """
    Process a single PDF file through OCR with retry logic.
    Uses Processing folder to avoid file lock conflicts with PDF24.

    Args:
        file_path: Path to the input PDF
        output_folder: Folder to save OCR'd PDF
        language: OCR language(s)
        deskew: Enable deskew
        clean: Not used (kept for API compatibility)
        delete_on_success: Delete input file after successful processing
        max_retries: Maximum retry attempts on failure (default: 2)
        error_folder: Folder to move failed files (optional)
        processing_folder: Temp folder for files being processed (optional)

    Returns:
        ProcessingResult with status and details
    """
    file_name = os.path.basename(file_path)
    output_path = os.path.join(output_folder, file_name)
    start_time = datetime.now()
    last_error = None
    working_path = file_path  # Will be updated if using processing folder

    logger.info(f"Starting OCR for: {file_name}")

    # Check if output already exists (skip if already processed)
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        logger.info(f"Output already exists, skipping: {file_name}")
        # Clean up input if it exists and delete_on_success is True
        if delete_on_success and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        return ProcessingResult(
            file_name=file_name,
            success=True,
            message="Already processed (output exists)"
        )

    # Check if input file still exists (race condition prevention)
    if not os.path.exists(file_path):
        logger.warning(f"Input file no longer exists: {file_name}")
        return ProcessingResult(
            file_name=file_name,
            success=False,
            message="File not found",
            error="Input file was removed or moved"
        )

    # Move to processing folder if specified (eliminates WinError 32)
    if processing_folder:
        working_path = move_to_processing_folder(file_path, processing_folder)
        if not working_path:
            return ProcessingResult(
                file_name=file_name,
                success=False,
                message="Could not move to processing folder",
                error="File move failed"
            )

    # Build command using working_path (either original or in processing folder)
    cmd = build_ocr_command(working_path, output_path, language, deskew)

    logger.debug(f"Command: {' '.join(cmd)}")

    # Retry loop
    for attempt in range(max_retries):

        try:
            # Clean up any partial output from previous attempt
            cleanup_partial_output(output_path)

            # Run PDF24 OCR CLI using Popen for better process control
            # Use HIGH_PRIORITY_CLASS for maximum performance
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.HIGH_PRIORITY_CLASS

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creation_flags
            )

            try:
                stdout, stderr = process.communicate(timeout=600)  # 10 minute timeout
            except subprocess.TimeoutExpired:
                # Kill ONLY this specific process tree on timeout
                logger.warning(f"TIMEOUT: {file_name} (attempt {attempt + 1}/{max_retries}) - killing specific process...")
                kill_process_tree(process.pid)
                process.kill()
                try:
                    process.communicate(timeout=5)
                except:
                    pass
                cleanup_partial_output(output_path)
                last_error = "Processing exceeded 10 minute limit"

                if attempt < max_retries - 1:
                    logger.info(f"Retrying {file_name}...")
                    time.sleep(2)
                    continue
                else:
                    processing_time = (datetime.now() - start_time).total_seconds()
                    if error_folder:
                        move_to_error_folder(working_path, error_folder)
                    return ProcessingResult(
                        file_name=file_name,
                        success=False,
                        message=f"Timeout after {max_retries} attempts",
                        error=last_error,
                        processing_time=processing_time
                    )

            processing_time = (datetime.now() - start_time).total_seconds()

            # Check if output was created
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                # Success - delete from processing folder (no lock conflict)
                if delete_on_success:
                    try:
                        # Small delay to ensure PDF24 releases handle
                        time.sleep(0.3)
                        os.remove(working_path)
                        logger.debug(f"Deleted processed file: {file_name}")
                    except Exception as e:
                        logger.warning(f"Could not delete {file_name}: {e}")

                return ProcessingResult(
                    file_name=file_name,
                    success=True,
                    message=f"Processed successfully",
                    processing_time=processing_time
                )
            else:
                # Output not created - remove ONLY the partial output for this file
                cleanup_partial_output(output_path)
                
                # Capture specific error details for diagnostic
                error_details = []
                if stdout: error_details.append(f"STDOUT: {stdout.strip()[-200:]}")
                if stderr: error_details.append(f"STDERR: {stderr.strip()[-500:]}")
                
                last_error = " | ".join(error_details) or "Output file not created"
                logger.warning(f"FAILED: {file_name} (attempt {attempt + 1}/{max_retries}) - {last_error}")

                if attempt < max_retries - 1:
                    logger.info(f"Retrying {file_name}...")
                    time.sleep(2)  # Brief pause before retry
                    continue
                else:
                    logger.error(f"FAILED: {file_name} - all {max_retries} attempts failed")
                    # Move to error folder
                    if error_folder:
                        move_to_error_folder(working_path, error_folder)
                    return ProcessingResult(
                        file_name=file_name,
                        success=False,
                        message=f"OCR failed after {max_retries} attempts",
                        error=last_error,
                        processing_time=processing_time
                    )

        except Exception as e:
            # Kill any hanging PDF24 processes on crash
            kill_pdf24_processes()
            cleanup_partial_output(output_path)
            last_error = str(e)

            if attempt < max_retries - 1:
                logger.warning(f"ERROR: {file_name} (attempt {attempt + 1}/{max_retries}) - {last_error}")
                logger.info(f"Retrying {file_name}...")
                time.sleep(2)
                continue
            else:
                processing_time = (datetime.now() - start_time).total_seconds()
                logger.error(f"ERROR: {file_name} - all {max_retries} attempts failed - {last_error}")
                # Move to error folder
                if error_folder:
                    move_to_error_folder(working_path, error_folder)
                return ProcessingResult(
                    file_name=file_name,
                    success=False,
                    message=f"Processing error after {max_retries} attempts",
                    error=last_error,
                    processing_time=processing_time
                )

    # Should never reach here, but just in case
    processing_time = (datetime.now() - start_time).total_seconds()
    return ProcessingResult(
        file_name=file_name,
        success=False,
        message="Unknown error",
        error=last_error or "Unexpected exit from retry loop",
        processing_time=processing_time
    )


def move_to_duplicate_folder(file_path: str, duplicate_folder: str) -> bool:
    """Move a duplicate file to the duplicate folder"""
    try:
        if not os.path.exists(duplicate_folder):
            os.makedirs(duplicate_folder)

        file_name = os.path.basename(file_path)
        dup_path = os.path.join(duplicate_folder, file_name)

        # If file already exists in duplicate folder, add timestamp
        if os.path.exists(dup_path):
            name, ext = os.path.splitext(file_name)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dup_path = os.path.join(duplicate_folder, f"{name}_{timestamp}{ext}")

        shutil.move(file_path, dup_path)
        logger.info(f"Moved duplicate file: {file_name}")
        return True
    except Exception as e:
        logger.error(f"Could not move duplicate file: {e}")
        return False


def get_pending_files(input_folder: str, output_folder: str, duplicate_folder: str = None, error_folder: str = None) -> list:
    """
    Get list of PDF files that haven't been processed yet.
    Moves duplicates (already in output) to duplicate folder if provided.
    Moves non-PDF files to error folder if provided.

    Args:
        input_folder: Folder with input PDFs
        output_folder: Folder with processed PDFs
        duplicate_folder: Folder to move duplicates (optional)
        error_folder: Folder to move non-PDF files (optional)

    Returns:
        List of file paths that need processing
    """
    try:
        if not os.path.exists(input_folder):
            return []

        # Get all files in input folder
        all_files = os.listdir(input_folder)

        # Move non-PDF files to error folder
        if error_folder:
            for file_name in all_files:
                if not file_name.lower().endswith('.pdf'):
                    input_path = os.path.join(input_folder, file_name)
                    if os.path.isfile(input_path):  # Skip directories
                        logger.warning(f"Non-PDF file detected: {file_name} - moving to Error folder")
                        move_to_error_folder(input_path, error_folder)

        # Get all PDFs in input folder
        input_files = [
            f for f in os.listdir(input_folder)
            if f.lower().endswith('.pdf')
        ]

        # Filter out already processed (check if output exists)
        # NOTE: Don't delete here - causes race condition with parallel workers
        pending = []
        for file_name in input_files:
            input_path = os.path.join(input_folder, file_name)
            output_path = os.path.join(output_folder, file_name)

            if not os.path.exists(output_path):
                pending.append(input_path)

        return sorted(pending)
    except PermissionError as e:
        logger.error(f"Permission denied accessing folder: {e}")
        return []
    except OSError as e:
        logger.error(f"Error accessing folder: {e}")
        return []


def get_processed_count(output_folder: str) -> int:
    """Get count of already processed files in output folder"""
    if not os.path.exists(output_folder):
        return 0
    return len([f for f in os.listdir(output_folder) if f.lower().endswith('.pdf')])


def cleanup_processed_inputs(input_folder: str, output_folder: str) -> int:
    """
    Delete input files that have already been processed (output exists).
    Call this AFTER batch processing completes to avoid race conditions.

    Returns:
        Number of files cleaned up
    """
    cleaned = 0
    try:
        if not os.path.exists(input_folder):
            return 0

        input_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]

        for file_name in input_files:
            input_path = os.path.join(input_folder, file_name)
            output_path = os.path.join(output_folder, file_name)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                try:
                    os.remove(input_path)
                    logger.info(f"Storage Cleanup: Deleted processed input {file_name}")
                    cleaned += 1
                except Exception as e:
                    logger.warning(f"Could not delete {file_name}: {e}")

        return cleaned
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        return cleaned

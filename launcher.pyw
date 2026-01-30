"""
Smart Launcher for PDF24 OCR Processor
- Checks if Streamlit is already running on port 8501
- If yes: just opens browser
- If no: starts Streamlit in background, then opens browser
"""
import subprocess
import socket
import webbrowser
import time
import sys
import os

# Configuration
PORT = 8501
URL = f"http://localhost:{PORT}"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_FILE = os.path.join(APP_DIR, "app.py")


def is_port_in_use(port):
    """Check if a port is already in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def start_streamlit():
    """Start Streamlit in background"""
    # Use pythonw to run without console window
    python_exe = sys.executable
    if python_exe.endswith('python.exe'):
        pythonw_exe = python_exe.replace('python.exe', 'pythonw.exe')
        if os.path.exists(pythonw_exe):
            python_exe = pythonw_exe

    # Start Streamlit as background process
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE

    subprocess.Popen(
        [python_exe, "-m", "streamlit", "run", APP_FILE,
         "--server.port", str(PORT),
         "--server.headless", "true"],
        cwd=APP_DIR,
        startupinfo=startupinfo,
        creationflags=subprocess.CREATE_NO_WINDOW
    )


def main():
    if is_port_in_use(PORT):
        # Streamlit already running, just open browser
        webbrowser.open(URL)
    else:
        # Start Streamlit
        start_streamlit()

        # Wait for server to start (max 10 seconds)
        for _ in range(20):
            time.sleep(0.5)
            if is_port_in_use(PORT):
                break

        # Open browser
        webbrowser.open(URL)


if __name__ == "__main__":
    main()

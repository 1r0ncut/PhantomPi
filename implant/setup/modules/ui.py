"""
PhantomPi Setup — Console UI Helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides colored terminal output, progress banners, and a shell-command
runner that respects the --debug flag.
"""

from __future__ import annotations

import subprocess
import sys
import shutil


# ---------------------------------------------------------------------------
# ANSI colour palette
# ---------------------------------------------------------------------------
class Colors:
    """ANSI escape sequences — only used when stdout is a TTY."""

    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    MAGENTA = "\033[95m"


# If output is not a terminal, strip colours so log files stay clean.
if not sys.stdout.isatty():
    for attr in dir(Colors):
        if not attr.startswith("_"):
            setattr(Colors, attr, "")


# ---------------------------------------------------------------------------
# UI helper class
# ---------------------------------------------------------------------------
class UI:
    """Centralised console output with colour, step tracking, and cmd runner."""

    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self._width = min(shutil.get_terminal_size().columns, 72)

    # -- Banner & sections --------------------------------------------------

    def banner(self):
        """Print the opening PhantomPi banner."""
        C = Colors
        w = self._width
        print()
        print(f"{C.CYAN}{C.BOLD}{'=' * w}{C.RESET}")
        lines = [
            "",
            "  ____  _                 _                  ____  _ ",
            " |  _ \\| |__   __ _ _ __ | |_ ___  _ __ ___|  _ \\(_)",
            " | |_) | '_ \\ / _` | '_ \\| __/ _ \\| '_ ` _ \\ |_) | |",
            " |  __/| | | | (_| | | | | || (_) | | | | |  __/| |",
            " |_|   |_| |_|\\__,_|_| |_|\\__\\___/|_| |_| |_|   |_|",
            "",
        ]
        for line in lines:
            print(f"{C.CYAN}{C.BOLD}{line.center(w)}{C.RESET}")
        subtitle = "Automated Implant Setup"
        print(f"{C.WHITE}{C.BOLD}{subtitle.center(w)}{C.RESET}")
        print(f"{C.CYAN}{C.BOLD}{'=' * w}{C.RESET}")
        print()

    def step(self, num: int, total: int, title: str):
        """Print a major-step header bar."""
        C = Colors
        w = self._width
        print()
        print(f"{C.CYAN}{'-' * w}{C.RESET}")
        print(f"{C.CYAN}{C.BOLD}  STEP {num}/{total} - {title}{C.RESET}")
        print(f"{C.CYAN}{'-' * w}{C.RESET}")

    # -- Message helpers ----------------------------------------------------

    def info(self, msg: str):
        """Informational message (cyan bullet)."""
        print(f"  {Colors.CYAN}[*]{Colors.RESET} {msg}")

    def success(self, msg: str):
        """Success message (green check)."""
        print(f"  {Colors.GREEN}[+]{Colors.RESET} {msg}")

    def warning(self, msg: str):
        """Warning message (yellow exclamation)."""
        print(f"  {Colors.YELLOW}[!]{Colors.RESET} {msg}")

    def error(self, msg: str):
        """Error message (red cross)."""
        print(f"  {Colors.RED}[-]{Colors.RESET} {msg}")

    def debug(self, msg: str):
        """Debug message — only shown when --debug is active."""
        if self.debug_mode:
            print(f"  {Colors.DIM}[D] {msg}{Colors.RESET}")

    def skipped(self, msg: str):
        """Skipped-item message (yellow circle)."""
        print(f"  {Colors.YELLOW}[>]{Colors.RESET} {Colors.YELLOW}{msg}{Colors.RESET}")

    # -- Final summary ------------------------------------------------------

    def summary(self, skipped_items: list, failures: list | None = None):
        """Print the closing summary box with failures (red) and skipped (yellow)."""
        C = Colors
        w = self._width
        failures = failures or []

        print()
        print(f"{C.CYAN}{'=' * w}{C.RESET}")

        if failures:
            print(
                f"{C.RED}{C.BOLD}"
                f"  FAILED — these steps need manual intervention:"
                f"{C.RESET}"
            )
            print()
            for idx, item in enumerate(failures, 1):
                print(f"  {C.RED}{idx}.{C.RESET} {item}")

        if skipped_items:
            if failures:
                print()
                print(
                    f"{C.YELLOW}{C.BOLD}"
                    f"  SKIPPED — optional items still pending:"
                    f"{C.RESET}"
                )
            else:
                print(
                    f"{C.YELLOW}{C.BOLD}"
                    f"  Setup complete — the following items need attention:"
                    f"{C.RESET}"
                )
            print()
            for idx, item in enumerate(skipped_items, 1):
                print(f"  {C.YELLOW}{idx}.{C.RESET} {item}")

        if not failures and not skipped_items:
            print(f"{C.GREEN}{C.BOLD}  Setup complete — implant is ready to go!{C.RESET}")

        print()
        print(f"{C.CYAN}{'=' * w}{C.RESET}")
        print()

    # -- Shell command runner -----------------------------------------------

    def run(self, cmd: str, *, check: bool = True, capture: bool = True,
            timeout: int = 300) -> subprocess.CompletedProcess:
        """
        Execute a shell command.

        Parameters
        ----------
        cmd     : shell command string
        check   : raise on non-zero exit code
        capture : capture stdout/stderr (False → inherit terminal)
        timeout : seconds before TimeoutExpired

        Returns
        -------
        subprocess.CompletedProcess
        """
        self.debug(f"$ {cmd}")
        try:
            result = subprocess.run(
                cmd, shell=True,
                capture_output=capture, text=True,
                timeout=timeout,
            )
            # Show a few lines of stdout in debug mode
            if capture and result.stdout and self.debug_mode:
                for line in result.stdout.strip().splitlines()[:5]:
                    self.debug(f"  stdout: {line}")
            if result.returncode != 0:
                if capture and result.stderr and self.debug_mode:
                    for line in result.stderr.strip().splitlines()[:5]:
                        self.debug(f"  stderr: {line}")
                if check:
                    raise RuntimeError(
                        f"Command exited {result.returncode}: {cmd}"
                    )
            return result
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Command timed out ({timeout}s): {cmd}")

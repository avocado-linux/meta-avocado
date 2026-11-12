"""The only module that starts processes.

Standard library only. Nothing here uses a shell. ``stream`` runs the flash
script and never signals it: an interrupt waits for the script to finish,
because killing it mid-write could leave the board half-flashed. ``capture``
is for short commands only; ``subprocess.run`` kills its child on
KeyboardInterrupt, which is acceptable for a listing or a sudo refresh and
which the CLI reports as an interrupted run.
"""

import signal
import subprocess
from pathlib import Path

from . import FlashError


class Interrupted(FlashError):
    """The operator interrupted the tool while the script ran."""


class SubprocessRunner:
    def capture(self, argv):
        """Run argv to completion; return (returncode, stdout).

        An executable that cannot start returns (127, <error text>) so
        callers can tell that apart from a command that ran.
        """
        try:
            proc = subprocess.run(
                list(argv),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except OSError as e:
            return 127, str(e)
        return proc.returncode, proc.stdout

    def stream(self, invocation, log_path, echo=print):
        """Run the script, echoing and logging each line in order.

        Standard error is merged into standard output and standard input is
        inherited so sudo can prompt. Returns the exit status. SIGINT is
        absorbed once the child runs (the terminal's signal already reached
        its process group, and this process never signals it): the wait
        continues however many times it arrives, keeps logging what the
        child prints, then raises Interrupted exactly once. A script that
        cannot start raises FlashError naming the log and its directory.
        """
        interrupted = False

        def absorb(signum, frame):
            nonlocal interrupted
            interrupted = True

        workdir = Path(log_path).parent
        try:
            log = open(log_path, "w", encoding="utf-8")
        except OSError as exc:
            raise FlashError(f"cannot open the log {log_path} in {workdir}: {exc}") from exc
        with log:
            try:
                proc = subprocess.Popen(
                    list(invocation.argv),
                    env=invocation.env,
                    cwd=invocation.cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                raise FlashError(
                    f"cannot start {invocation.argv[0]}: {exc} "
                    f"(work directory: {workdir}, log: {log_path})"
                ) from exc
            # Installed after the spawn: a custom or ignored disposition set
            # before it would be inherited by the child.
            installed = True
            try:
                previous = signal.signal(signal.SIGINT, absorb)
            except ValueError:  # not the main thread: the loop below still copes
                installed = False
            try:
                while True:
                    try:
                        for line in proc.stdout:
                            line = line.rstrip("\n")
                            log.write(line + "\n")
                            log.flush()
                            if not interrupted:
                                echo(line)
                        proc.wait()
                        break
                    except KeyboardInterrupt:
                        # Keep draining so the child never blocks on a full
                        # pipe; further lines go to the log only.
                        interrupted = True
            finally:
                if installed:
                    # None means the old handler was not set from Python.
                    signal.signal(signal.SIGINT, previous or signal.SIG_DFL)
                proc.stdout.close()
        if interrupted:
            raise Interrupted("interrupted while the provisioning script ran")
        return proc.returncode

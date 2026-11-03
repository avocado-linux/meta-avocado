"""The only module that starts processes.

Standard library only. Nothing here uses a shell, and nothing here signals
a child: an interrupt waits for the flash script to finish, because killing
it mid-write could leave the board half-flashed.
"""

import subprocess

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
        inherited so sudo can prompt. Returns the exit status. On
        KeyboardInterrupt the child is left alone (the terminal's signal
        already reached its process group): this waits for it to exit, keeps
        logging what it prints, then raises Interrupted.
        """
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                list(invocation.argv),
                env=invocation.env,
                cwd=invocation.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            interrupted = False
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
            proc.stdout.close()
        if interrupted:
            raise Interrupted("interrupted while the provisioning script ran")
        return proc.returncode

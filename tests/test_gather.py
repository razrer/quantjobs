"""Regression tests for `daily`'s concurrent gather phase.

Three things here are easy to get wrong and quiet when wrong: the politeness
guarantee (running sources side by side must not raise any one host's rate),
the report (six writers into one terminal shreds the output `alerts` exists to
produce), and failure isolation (one broken source must not take the other
eight, which is the contract `daily` has always had).

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import io
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

import argparse
import contextlib
import re
from pathlib import Path

from quantscraper import cli, http


class ThrottleIsPerHostTest(unittest.TestCase):
    """The precondition for the whole phase, and the thing that would make it
    a politeness regression if it were false."""

    def setUp(self):
        self._saved = dict(http._last_hit)
        http._last_hit.clear()
        self.addCleanup(lambda: (http._last_hit.clear(),
                                 http._last_hit.update(self._saved)))

    def _book(self, host, slots):
        for _ in range(slots):
            http._throttle(host)

    def test_different_hosts_do_not_wait_for_each_other(self):
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda h: self._book(h, 3), ("a.test", "b.test", "c.test")))
        elapsed = time.monotonic() - started
        # Three slots on one host is two intervals of waiting; three hosts in
        # parallel must cost the same, not three times as much.
        self.assertLess(elapsed, 2 * http.MIN_INTERVAL_S + 1.0)

    def test_one_host_is_still_serialised_however_many_threads_ask(self):
        """**The politeness test.** Concurrency across sources must not become
        concurrency against a source: twelve callers to one host still take
        eleven intervals, exactly as one caller making twelve requests would."""
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self._book("one.test", 3), range(4)))
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 11 * http.MIN_INTERVAL_S - 0.5)

    def test_a_slower_host_keeps_its_own_interval(self):
        """A host in `HOST_INTERVAL_S` must not inherit the default because it
        happens to be running beside faster ones."""
        slow = next(iter(http.HOST_INTERVAL_S))
        started = time.monotonic()
        self._book(slow, 2)
        self.assertGreaterEqual(
            time.monotonic() - started, http.HOST_INTERVAL_S[slow] - 0.2
        )


class GatherTest(unittest.TestCase):
    def test_every_step_runs_and_the_report_is_whole(self):
        """Each step's output is printed as one block, in the order listed --
        not interleaved. A shredded report is the one `alerts` writes into."""
        def talker(name, lines):
            def step():
                for i in range(lines):
                    print(f"{name} line {i}")
                    time.sleep(0.005)
                return 0
            return step

        out = io.StringIO()
        saved = sys.stdout
        sys.stdout = out
        try:
            failed = cli._gather([
                ("alpha", talker("alpha", 8)),
                ("beta", talker("beta", 8)),
                ("gamma", talker("gamma", 8)),
            ])
        finally:
            sys.stdout = saved

        self.assertEqual(failed, [])
        text = out.getvalue()
        self.assertEqual(
            [line.split()[0] for line in text.splitlines() if "line" in line],
            ["alpha"] * 8 + ["beta"] * 8 + ["gamma"] * 8,
            "a step's output was interleaved with another's",
        )
        self.assertLess(text.index("=== alpha ==="), text.index("=== beta ==="))

    def test_they_really_do_run_at_once(self):
        """The point of the phase. Three steps that each sleep must cost one
        sleep, not three."""
        def sleeper():
            time.sleep(0.4)
            return 0

        started = time.monotonic()
        saved, sys.stdout = sys.stdout, io.StringIO()
        try:
            cli._gather([(f"s{i}", sleeper) for i in range(3)])
        finally:
            sys.stdout = saved
        self.assertLess(time.monotonic() - started, 0.9)

    def test_one_failing_step_does_not_take_the_others(self):
        """`daily`'s standing contract: a board redesigned underneath us costs
        its own postings and not the other eight sources'."""
        ran = []

        def ok(name):
            def step():
                ran.append(name)
                return 0
            return step

        def explode():
            raise RuntimeError("the board changed shape")

        saved, sys.stdout = sys.stdout, io.StringIO()
        errs, sys.stderr = sys.stderr, io.StringIO()
        try:
            failed = cli._gather([
                ("good", ok("good")), ("bad", explode), ("other", ok("other")),
            ])
            reported = sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = saved, errs

        self.assertEqual(failed, ["bad"])
        self.assertEqual(sorted(ran), ["good", "other"])
        self.assertIn("the board changed shape", reported)

    def test_a_nonzero_exit_code_counts_as_failed(self):
        saved, sys.stdout = sys.stdout, io.StringIO()
        try:
            failed = cli._gather([("quiet", lambda: 1), ("fine", lambda: 0)])
        finally:
            sys.stdout = saved
        self.assertEqual(failed, ["quiet"])

    def test_stderr_is_kept_separate_from_stdout(self):
        """`daily`'s exit code and `alerts`' FAIL lines both live on stderr,
        and folding them into stdout would hide which source went quiet."""
        def noisy():
            print("this is the result")
            print("  FAIL something went quiet", file=sys.stderr)
            return 1

        out, err = io.StringIO(), io.StringIO()
        saved_out, saved_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            cli._gather([("noisy", noisy)])
        finally:
            sys.stdout, sys.stderr = saved_out, saved_err
        self.assertIn("this is the result", out.getvalue())
        self.assertNotIn("FAIL", out.getvalue())
        self.assertIn("FAIL something went quiet", err.getvalue())

    def test_an_empty_phase_is_not_an_error(self):
        self.assertEqual(cli._gather([]), [])

    def test_only_the_cli_prints_so_nothing_escapes_the_capture(self):
        """**The capture is complete only because the library is silent.**

        `_ThreadStream` routes by thread, and a step's own thread is the one
        that claimed a buffer -- so anything printed from inside `jobs`' or
        `pages`' twelve-worker pools would fall through to the real terminal
        and shred the report, invisibly and only under concurrency. It does not
        happen today because the modules under `quantscraper/` print nothing at
        all: reporting lives in `cli.py`. This is the guard for the day someone
        adds a debug line to a worker.
        """
        import re
        from pathlib import Path

        root = Path(cli.__file__).resolve().parent
        offenders = []
        for module in sorted(root.rglob("*.py")):
            if module.name == "cli.py":
                continue
            for number, line in enumerate(
                module.read_text(encoding="utf-8").splitlines(), 1
            ):
                if re.match(r"\s*print\(", line):
                    offenders.append(f"{module.relative_to(root)}:{number}")
        self.assertEqual(
            offenders, [],
            "a module outside cli.py prints; if it runs on a worker thread its"
            " output will escape the gather phase's per-step capture",
        )

    def test_the_stream_falls_back_for_threads_that_claimed_nothing(self):
        """A library that logs from its own thread pool -- `jobs` and `pages`
        each run twelve -- must not lose its output into nowhere."""
        fallback = io.StringIO()
        stream = cli._ThreadStream(fallback)
        done = threading.Event()

        def unclaimed():
            stream.write("from an unclaimed thread\n")
            done.set()

        threading.Thread(target=unclaimed).start()
        done.wait(2)
        self.assertIn("from an unclaimed thread", fallback.getvalue())


class EverySubcommandHasAHandlerTest(unittest.TestCase):
    """The dispatch table and the parser are two lists of the same commands.

    They were one chain of `if args.command == ...` and are now a dict, which
    is shorter and moves the failure: a subparser added without an entry used
    to fall through to `fetch` and silently pull every registry, and now raises
    `KeyError` at the moment it is typed. Neither is something to discover from
    a scheduled run, so the two lists are compared here instead.
    """

    def _registered(self):
        parser = _build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                return set(action.choices)
        self.fail("no subparsers on the parser")

    def test_the_two_lists_are_the_same(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        block = source[source.index("    handlers = {"):source.index("    return handlers[")]
        wired = set(re.findall(r'"([a-z_]+)": lambda', block))
        self.assertEqual(self._registered(), wired)


def _build_parser():
    """`cli.main`'s parser, without running a command.

    `main` builds and dispatches in one function, so the parser is reached by
    parsing something that cannot run -- `--help` exits, so a bad command is
    used instead and the parser is caught on the way past.
    """
    holder = {}
    real = argparse.ArgumentParser.parse_args

    def capture(self, argv=None, namespace=None):
        holder.setdefault("parser", self)
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture
    try:
        with contextlib.suppress(SystemExit):
            cli.main([])
    finally:
        argparse.ArgumentParser.parse_args = real
    return holder["parser"]


if __name__ == "__main__":
    unittest.main()

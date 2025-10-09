#!/usr/bin/env python3

"""
CMPUT 455 assignment 2 testing script

usage: python a2test.py [-h] [-v] your_submission test

positional arguments:
  your_submission  Path to your submissions .py file
  test             Path to the tests .txt file

optional arguments:
  -h, --help       show this help message and exit
  -v, --verbose    Print more output
"""

import argparse
import contextlib
from functools import partial
import math
from operator import itemgetter
import os
import select
from subprocess import Popen, PIPE
import sys
from dataclasses import dataclass
from pathlib import Path
import re
import time
from typing import Callable, Iterator, Sequence, IO, Tuple, TypeVar, Union
from itertools import chain, starmap, zip_longest
from multiprocessing.pool import ThreadPool
import multiprocessing

T = TypeVar("T")

# Default maximum command execution time in seconds
CURRENT_SOLVE_TIMELIMIT = 1  # default matches your program’s default
DEFAULT_TIMEOUT = 1
USE_COLOR = True
STATUS_PATTERN = re.compile(r"^= .*")

# Color codes
RED = "\033[31m"
GREEN = "\033[32m"
BLUE = "\033[34m"
RESET = "\033[0m"

def color_print(*args, color, **kwargs):
    if not USE_COLOR:
        return print(*args, **kwargs)
    print(color, end="")
    print(*args, **kwargs)
    print(RESET, end="")

def timed(fn: Callable[[], T], timeout: float) -> Tuple[bool, T]:
    try:
        pool = ThreadPool(processes=1)
        result = pool.apply_async(fn)
        return True, result.get(timeout=timeout)
    except multiprocessing.TimeoutError:
        return False, None
    finally:
        pool.close()

class StudentProgram:
    __path: Path
    __process: Union[Popen, None] = None

    def __init__(self, submission: Path):
        self.__path = submission

    def kill(self):
        if self.__process is not None:
            self.__process.kill()
            self.__process = None

    def __assert_process(self):
        if self.__process is None:
            self.__process = self.__load_program()

    def run_command(self, cmd: str) -> "Test":
        self.__assert_process()
        # Will be raised if the process is forcibly killed
        with contextlib.suppress(OSError):
            return Test.from_process(cmd, self.__process)

    def run_test(self, test: "Test", timeout_secs: Union[float, None] = None) -> "Test":
        if timeout_secs is None:
            timeout_secs = DEFAULT_TIMEOUT
        
        # If this command is `timelimit N`, remember it for the *next* solve
        if test.command.startswith("timelimit"):
            try:
                _, n = test.command.split()
                n = int(n)
                # update the global *at runtime* for subsequent solves
                global CURRENT_SOLVE_TIMELIMIT
                CURRENT_SOLVE_TIMELIMIT = n
            except Exception:
                pass

        # If this specific test line sets a per-command timeout (your current behavior), use it.
        if test.dynamic_timeout is not None:
            timeout_secs = test.dynamic_timeout

        # Small cushion
        timeout_secs += 0.25

        # if this is a solve command, add the *current* timelimit set earlier
        if test.command.split()[0] == "solve":
            timeout_secs += CURRENT_SOLVE_TIMELIMIT

        ok, result = timed(partial(self.run_command, test.command), timeout_secs)
        if ok:
            return result
        error_text = Test.get_error_text(self.__process.stderr)
        self.kill()
        return TestTimeout(test, timeout_secs, error_text)


    def __load_program(self) -> Popen:
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            return Popen(
                ("python3", "-u", self.__path),  # <- -u ensures unbuffered stdio
                stdin=PIPE, stdout=PIPE, stderr=PIPE,
                text=True, env=env
            )
        except Exception as e:
            print(e)
            print(f"Failed to run `python3 '{self.__path}'`")
            sys.exit(1)


@dataclass(frozen=True)
class Invocation:
    submission: Path
    test: Path
    verbose: bool

    @staticmethod
    def from_args() -> "Invocation":
        parser = argparse.ArgumentParser(prog=f"python {sys.argv[0]}")
        parser.add_argument("your_submission", help="Path to your submissions .py file")
        parser.add_argument("test", help="Path to the tests .txt file")
        parser.add_argument("-v", "--verbose", action="store_true", help="Print more output")
        args = parser.parse_args()
        inv = Invocation(Path(args.your_submission), Path(args.test), args.verbose)
        assert inv.submission.exists(), f"invalid file path '{args.your_submission}'"
        assert inv.test.exists(), f"invalid file path '{args.test}'"
        return inv

def iterlines(file: IO):
    while True:
        yield file.readline()

@dataclass(frozen=True)
class Test:
    command: str
    status: str
    counts_for_marks: bool
    dynamic_timeout: Union[int, None]
    error_output: str

    class IncompleteTestParse(Exception):
        pass

    @staticmethod
    def __parse_command(line: str, marking: bool) -> Tuple[bool, bool, str]:
        counts_for_marks = False
        dynamic_timeout = None
        if not marking:
            return counts_for_marks, dynamic_timeout, line
        if line.startswith("?"):
            line = line[1:]
            counts_for_marks = True
        timelimit_pattern = re.compile(r"^timelimit\s+(\d+)\s*$")
        match = timelimit_pattern.match(line)
        if match is not None:
            dynamic_timeout = int(match.group(1))

        
        return counts_for_marks, dynamic_timeout, line

    @staticmethod
    def __parse_command_body(lines: Iterator[str]) -> Tuple[str, str]:
        result = []
        for line in lines:
            if STATUS_PATTERN.match(line):
                status = line
                break
            else:
                result.append(line)
        else:
            raise Test.IncompleteTestParse("did not find status line")
        return tuple(result), status

    @staticmethod
    def from_parse(lines: Iterator[str], marking: bool) -> "Test":
        # Remove comments and strip whitespace
        whitepace = re.compile(r"^\s*#|^\s*$")
        lines = (line.strip() for line in lines if not whitepace.match(line))
        counts_for_marks, dynamic_timeout, command = Test.__parse_command(next(lines), marking)
        result, status = Test.__parse_command_body(lines)
        shared_args = (command, status, counts_for_marks, dynamic_timeout, "")
        if marking and len(result) and result[0].startswith("@"):
            return TestPattern(*shared_args, re.compile("\n".join(result)[1:], re.DOTALL))
        return TestLines(*shared_args, result)

    @staticmethod
    def from_test_file(test: Path) -> Tuple["Test", ...]:
        lines = iter(test.read_text().split("\n"))
        def consume():
            try:
                while True:
                    yield Test.from_parse(lines, marking=True)
            except (StopIteration, Test.IncompleteTestParse):
                pass
        return tuple(consume())

    @staticmethod
    def get_error_text(file: IO) -> str:
        poller = select.poll()
        poller.register(file.fileno(), select.POLLIN)
        os.set_blocking(file.fileno(), False)
        error_text = ""
        while any(event & select.POLLIN for _, event in poller.poll(0)):
            error_text += file.read()
        return error_text

    @staticmethod
    def from_process(command: str, process: Popen) -> "Test":
        assert process.stdin is not None
        process.stdin.write(f"{command}\n")
        process.stdin.flush()
        assert process.stdout is not None
        lines = iterlines(process.stdout)
        test = Test.from_parse(chain((command,), lines), marking=False)
        assert process.stderr is not None
        error_text = Test.get_error_text(process.stderr)
        object.__setattr__(test, "error_output", error_text)
        return test

@dataclass(frozen=True)
class TestLines(Test):
    result: Tuple[str, ...]

@dataclass(frozen=True)
class TestPattern(Test):
    pattern: re.Pattern

@dataclass(frozen=True)
class TestTimeout(Test):
    timeout: Union[int, float]

    def __init__(self, test: Test, timeout: Union[int, float], error_output: str):
        for field in Test.__annotations__:
            object.__setattr__(self, field, getattr(test, field))
        object.__setattr__(self, "status", "")
        object.__setattr__(self, "timeout", timeout)
        object.__setattr__(self, "error_output", error_output)

@dataclass(frozen=True)
class TestResult:
    answer_key: Test
    student: Test
    status_matches: bool
    output_matches: bool
    time_out: bool

    @property
    def status_and_output_matches(self):
        return self.status_matches and self.output_matches

    @staticmethod
    def from_comparison(answer_key: Test, student: Test) -> "TestResult":
        if type(student) is TestTimeout:
            return TestResult(answer_key, student, False, False, True)
        status_matches = answer_key.status == student.status
        assert type(student) is TestLines
        if type(answer_key) is TestPattern:
            output_matches = bool(answer_key.pattern.match("\n".join(student.result)))
        else:
            assert type(answer_key) is TestLines
            output_matches = answer_key.result == student.result
        return TestResult(answer_key, student, status_matches, output_matches, False)
    
    @staticmethod
    def from_comparisons(answer_key: Sequence[Test], student: Sequence[Test]) -> Tuple["TestResult", ...]:
        return tuple(starmap(TestResult.from_comparison, zip(answer_key, student)))

    def print_verbose(self):
        print(f"Command: {self.answer_key.command}")
        if type(self.student) is TestTimeout:
            color_print(f"Program timed out after {self.student.timeout} seconds", color=RED)
        elif self.output_matches:
            color_print("Output from command matches expected output", color=GREEN)
        elif type(self.answer_key) is TestPattern:
            print("Expected output matching the following regular expression:")
            color_print(self.answer_key.pattern.pattern, color=GREEN)
            print("Received:")
            color_print(*self.student.result, sep="\n", color=RED)
        elif type(self.answer_key) is TestLines:
            print("Expected:")
            color_print(*self.answer_key.result, sep="\n", color=GREEN)
            print("Received:")
            answer_key = "\n".join(self.answer_key.result)
            student = "\n".join(self.student.result)
            print_colored_diff(answer_key, student)
        else:
            raise Exception()

        print()

        if type(self.student) is TestTimeout:
            pass
        elif self.status_matches:
            color_print("Resulting status code is correct", color=GREEN)
        else:
            print("Expected status code:")
            color_print(self.answer_key.status, color=GREEN)
            print("Received status code:")
            print_colored_diff(self.answer_key.status, self.student.status)

        print()

        if self.student.error_output:
            print("Program outputted the following error text:")
            color_print(self.student.error_output, color=RED)

        if self.answer_key.counts_for_marks:
            print("This test will be marked.")
        else:
            print("This test will NOT be marked.")
    
def print_colored_diff(correct: str, incorrect: str):
    for corr, inc in zip_longest(correct, incorrect):
        if inc is None:
            break
        color = GREEN if corr == inc else RED
        color_print(inc, color=color, sep="", end="")
    print()

def print_detailed_results(results: Sequence[TestResult]):
    for i, result in enumerate(results):
        if result.status_and_output_matches:
            continue
        print(f"=== Test {i} ===")
        result.print_verbose()
            

@dataclass(frozen=True)
class TestStatistics:
    test_count: int
    status_matches: int
    output_matches: int
    status_and_output_matches: int
    time_outs: int

    @staticmethod
    def from_test_results(results: Sequence[TestResult]):
        return TestStatistics(
            len(results),
            *(sum(1 for result in results if getattr(result, attr))
                for attr in ("status_matches", "output_matches", "status_and_output_matches", "time_out"))
        )

    def fraction(self, attr: str) -> str:
        return f"{getattr(self, attr)} / {self.test_count}"

    def color(self, attr: str) -> str:
        return GREEN if getattr(self, attr) == self.test_count else RED
    
    def color_inv(self, attr: str) -> str:
        return RED if getattr(self, attr) == self.test_count else GREEN
    
    def summarize(self):
        color_print("Summary report:", color=BLUE)
        print(f"{self.test_count} tests performed")
        color_print(f"{self.fraction('status_matches')} output statuses matched.", color=self.color("status_matches"))
        color_print(f"{self.fraction('output_matches')} command outputs matched.", color=self.color("output_matches"))
        color_print(f"{self.fraction('time_outs')} tests timed out.", color=self.color_inv("time_outs"))

    def marks(self):
        if self.test_count == 0:
            color_print("Nothing to mark", color=BLUE)
            return
        color_print("Marks report", color=BLUE)
        mark = round(math.floor(self.status_and_output_matches / self.test_count * 100) / 10, 1)
        if mark == 0 and self.status_and_output_matches != 0:
            mark = 0.1
        print(f"{self.status_and_output_matches} / {self.test_count} marked tests = {mark}% out of 10% for public tests.")

@dataclass(frozen=True)
class FullTestRun:
    results_all: TestResult
    stats_all: TestStatistics
    results_marked: TestResult
    stats_marked: TestStatistics

def test_submission(submission: Path, test: Path) -> FullTestRun:
    answer_key = Test.from_test_file(test)
    program = StudentProgram(submission)
    stu_tests = tuple(program.run_test(test, DEFAULT_TIMEOUT)
                for test in answer_key)
    results_all = TestResult.from_comparisons(answer_key, stu_tests)
    stats_all = TestStatistics.from_test_results(results_all)

    for_marks = tuple((key, stu) for key, stu in zip(answer_key, stu_tests) if key.counts_for_marks)
    answer_key_for_marks = tuple(map(itemgetter(0), for_marks))
    student_for_marks = tuple(map(itemgetter(1), for_marks))
    results_for_marks = TestResult.from_comparisons(answer_key_for_marks, student_for_marks)
    stats_for_marks = TestStatistics.from_test_results(results_for_marks)

    program.kill()

    return FullTestRun(results_all, stats_all, results_for_marks, stats_for_marks)
    

def main():
    t0 = time.time()
    invocation = Invocation.from_args()
    run_result = test_submission(invocation.submission, invocation.test)
    print_detailed_results(run_result.results_all)
    run_result.stats_all.summarize()
    run_result.stats_marked.marks()

    print("\nFinished after", round(time.time() - t0, 2), "seconds.")
    


if __name__ == "__main__" and not sys.flags.interactive:
    main()

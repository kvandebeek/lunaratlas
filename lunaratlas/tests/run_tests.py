"""Run LunarAtlas tests with an always-visible percentage.

Examples:
    python lunaratlas/tests/run_tests.py
    python lunaratlas/tests/run_tests.py --pattern 'test_ui.py'
"""
import argparse
import os
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))


class ProgressResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity, total):
        super().__init__(stream, descriptions, verbosity)
        self.total = total
        self.current = 0

    def startTest(self, test):
        self.current += 1
        percent = 100 * self.current / max(self.total, 1)
        self.stream.writeln(f'[{self.current}/{self.total} {percent:5.1f}%] {test.id()}')
        self.stream.flush()
        super().startTest(test)


class ProgressRunner(unittest.TextTestRunner):
    def __init__(self, total, **kwargs):
        super().__init__(**kwargs)
        self.total = total

    def _makeResult(self):
        return self.resultclass(self.stream, self.descriptions, self.verbosity, self.total)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pattern', default='test*.py', help='unittest discovery filename pattern')
    p.add_argument('-q', '--quiet', action='store_true', help="hide unittest's per-test result line (the percentage remains)")
    a = p.parse_args()
    suite = unittest.defaultTestLoader.discover(HERE, pattern=a.pattern, top_level_dir=HERE)
    total = suite.countTestCases()
    result = ProgressRunner(total, verbosity=1 if a.quiet else 2, resultclass=ProgressResult).run(suite)
    raise SystemExit(not result.wasSuccessful())


if __name__ == '__main__':
    main()

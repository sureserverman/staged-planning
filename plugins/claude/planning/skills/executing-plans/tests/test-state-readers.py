#!/usr/bin/env python3
"""Versioned projection controls alongside the frozen legacy reader suites."""
import sys
import unittest

from workflow_state_cases import ProjectionReaders

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProjectionReaders)
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())

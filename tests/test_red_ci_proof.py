"""Deliberately broken. Exists only on a throwaway branch to prove CI goes red. Never merge."""

import os


def test_always_fails():
    assert 1 == 2, "intentional failure for the red-CI proof"

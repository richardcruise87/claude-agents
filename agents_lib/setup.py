"""
Setup file for Claude Agents Shared Library.
"""
from setuptools import setup, find_packages

setup(
    name="agents-lib",
    version="1.0.0",
    description="Shared utilities for Claude-based automation agents",
    author="Richard Cruise",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        # No external dependencies - uses only stdlib
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)

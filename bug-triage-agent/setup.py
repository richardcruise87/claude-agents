"""
Setup script for Octavia Bug Triage Agent
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="octavia-bug-triage-agent",
    version="1.0.0",
    description="AI-powered bug triage agent for OpenStack Octavia",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Richard Cruise",
    url="https://github.com/richardcruise87/claude-agents",

    # Package discovery
    packages=find_packages(where="."),
    package_dir={"": "."},

    # Include package data (prompts, config samples)
    include_package_data=True,
    package_data={
        "": [
            "prompts/*.txt",
            "config.sample.json",
        ],
    },

    # Dependencies
    python_requires=">=3.8",
    install_requires=[
        "claude-agent-sdk",
        "agents-lib",  # Local shared library
    ],

    # Console scripts (command-line entry points)
    entry_points={
        "console_scripts": [
            "octavia-triage-bugs=bug_triage_agent:cli_main",
        ],
    },

    # Classifiers
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Bug Tracking",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)

"""Setup script for Octavia Backport Agent."""
from setuptools import setup, find_packages
from pathlib import Path

readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="octavia-backport-agent",
    version="1.0.0",
    description="Automated backport monitor and review agent for OpenStack Octavia",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Richard Cruise",
    url="https://github.com/richardcruise87/claude-agents",

    packages=find_packages(where="."),
    package_dir={"": "."},

    include_package_data=True,
    package_data={
        "": [
            "prompts/*.txt",
            "config.sample.json",
        ],
    },

    python_requires=">=3.8",
    install_requires=[
        "claude-agent-sdk",
        "agents-lib",
    ],

    entry_points={
        "console_scripts": [
            "octavia-backport-monitor=backport_monitor:cli_main",
            "octavia-backport-review=backport_review_agent:cli_main",
        ],
    },

    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.12",
    ],
)

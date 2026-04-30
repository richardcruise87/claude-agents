"""
Setup script for OpenStack CI Failure Analysis Agent
"""
from setuptools import setup, find_packages
from pathlib import Path

readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="openstack-ci-failure-agent",
    version="1.0.0",
    description="AI-powered CI failure analysis agent for OpenStack Zuul",
    long_description=long_description,
    long_description_content_type="text/markdown",
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
            "octavia-ci-agent=ci_failure_agent:cli_main",
            "octavia-analyze-ci=analyze_ci_failure:cli_main",
        ],
    },

    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Programming Language :: Python :: 3",
    ],
)

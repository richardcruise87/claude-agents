"""Setup script for DevStack Test Agent."""
from setuptools import setup, find_packages

setup(
    name="octavia-devstack-test-agent",
    version="1.0.0",
    description="AI-powered DevStack integration testing agent for OpenStack code reviews",
    author="Richard Cruise",
    author_email="rcruise@redhat.com",
    packages=find_packages(),
    py_modules=["devstack_test_agent", "config", "review_parser"],
    install_requires=[
        "claude-agent-sdk>=0.1.0",
        "agents-lib",
    ],
    entry_points={
        "console_scripts": [
            "octavia-devstack-test=devstack_test_agent:cli_main",
        ],
    },
    package_data={
        "": ["prompts/*.txt", "*.json"],
    },
    include_package_data=True,
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)

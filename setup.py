from setuptools import setup, find_packages
from pathlib import Path

long_description = Path(__file__).parent.joinpath("README.md").read_text(encoding="utf-8")

setup(
    name="traffic-orchestrator",
    version="2.1.0",
    description="Official Python client for Traffic Orchestrator license validation, management, and analytics",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Traffic Orchestrator",
    author_email="support@trafficorchestrator.com",
    url="https://trafficorchestrator.com/docs/sdks/python",
    packages=find_packages(),
    install_requires=[
        "requests>=2.0.0",
        "cryptography>=41.0.0",
        "pyjwt>=2.8.0"
    ],
    python_requires=">=3.8",
    keywords=["licensing", "license-validation", "traffic-orchestrator", "api-client", "saas"],
    license="MIT",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)

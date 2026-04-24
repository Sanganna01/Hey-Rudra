from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-16") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="heyrudra",
    version="0.1.0",
    author="Sanganna01",
    author_email="Sanganna01@users.noreply.github.com",
    description="Natural language to shell command converter with AI agents",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Sanganna01/Hey-Rudra.git",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Shells",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    include_package_data=True,
    package_data={
        "heyrudra": ["prompts/*.txt"],
    },
    py_modules=["cli", "langgraph_workflow", "session_context", "redis_client"],
    entry_points={
        "console_scripts": [
            "heyrudra=cli:main",
        ],
    },
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
        ],
    },
)
from setuptools import setup

def read_file(fname):
    with open(fname, 'r') as f:
        return f.read()

setup(name = "pyinotifyd",
    author = "Thomas Oettli",
    author_email = "spacefreak@noop.ch",
    description = "Monitoring filesystems events with inotify on Linux and execute tasks.",
    license = "GPL 3",
    keywords = "inotify daemon",
    url = "https://github.com/spacefreak86/pyinotifyd",
    packages = ["pyinotifyd"],
    long_description = read_file("README.md"),
    long_description_content_type = "text/markdown",
    classifiers = [
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Topic :: Utilities"
    ],
    include_package_data = True,
    entry_points = {
        "console_scripts": [
            "pyinotifyd=pyinotifyd:main"
        ]
    },
    install_requires = ["pyinotify"],
    python_requires = ">=3.7"
)

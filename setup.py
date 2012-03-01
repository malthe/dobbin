__version__ = '0.2'

import os
import sys

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.txt')).read()
NOTES = open(os.path.join(here, 'NOTES.txt')).read()
CHANGES = open(os.path.join(here, 'CHANGES.txt')).read()
USAGE = open(os.path.join(here, 'src', 'dobbin', 'README.txt')).read()

version = sys.version_info[:3]

install_requires = [
    "transaction",
    ]

setup(
    name="dobbin",
    version=__version__,
    description="Pure-Python object database.",
    long_description="\n\n".join((README, USAGE, NOTES, CHANGES)),
    classifiers=[
       "Development Status :: 3 - Alpha",
       "Intended Audience :: Developers",
       "Programming Language :: Python",
       "Topic :: Database",
       "Operating System :: POSIX",
      ],
    keywords="object database persistence",
    author="Malthe Borch",
    author_email="mborch@gmail.com",
    install_requires=install_requires,
    license='BSD',
    packages=find_packages('src'),
    package_dir = {'': 'src'},
    include_package_data=True,
    zip_safe=False,
    test_suite="dobbin.tests",
    tests_require = install_requires,
    )


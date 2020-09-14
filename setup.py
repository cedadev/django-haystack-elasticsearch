#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup
from setuptools import find_packages

with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

requirements = [
    'django-haystack>=2.5.1',
    'ceda-elasticsearch-tools'
]

dependency_links = [
    'git+https://github.com/cedadev/ceda-elasticsearch-tools.git'
]

test_requirements = [
    'python-dateutil',
    'geopy==0.95.1',

    'nose',
    'mock',
    'coverage',
]

setup(
    name='django-haystack-elasticsearch',
    version='2.0.1',
    description="A set of backends for using Elasticsearch on Haystack.",
    long_description=readme + '\n\n' + history,
    author="Bruno Marques",
    author_email='bruno@cravefood.services',
    url='https://github.com/CraveFood/django-haystack-elasticsearch',
    packages=find_packages(),
    include_package_data=True,
    install_requires=requirements,
    dependency_links=dependency_links,
    license="BSD license",
    zip_safe=False,
    keywords='haystack_elasticsearch',
    classifiers=[
        'Development Status :: 5 - Production',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
    test_suite='tests.run_tests.run_all',
    tests_require=test_requirements
)

#!/usr/bin/env python
# Installs dogslow.

import os
import sys
from distutils.core import setup

def long_description():
    """Get the long description from the README"""
    return open(os.path.join(sys.path[0], 'README.rst')).read()

setup(
    author='Erik van Zijst',
    author_email='erik.van.zijst@gmail.com',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Framework :: Django',
        'Intended Audience :: Developers',
        ('License :: OSI Approved :: '
         'GNU Library or Lesser General Public License (LGPL)'),
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.5',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Topic :: Software Development :: Debuggers',
        'Topic :: Utilities',
    ],
    description='A Django middleware that logs tracebacks of slow requests.',
    download_url=('https://bitbucket.org/evzijst/dogslow/downloads/'
                  'dogslow-0.9.4.tar.gz'),
    keywords='django debug watchdog middleware traceback',
    license='GNU LGPL',
    long_description=long_description(),
    name='dogslow',
    packages=['dogslow'],
    url='https://bitbucket.org/evzijst/dogslow',
    version='0.9.4',
)

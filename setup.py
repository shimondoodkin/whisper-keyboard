from pathlib import Path
from setuptools import setup, find_packages

long_description = Path('README.md').read_text(encoding='utf-8')

with open('requirements.txt') as f:
    required = f.read().splitlines()

setup(
    name='wkey',
    version='0.2',
    description='Integrate OpenAI speech-to-text Whisper with your keyboard',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/shimondoodkin/whisper-keyboard',
    author='shimondoodkin',
    license='MIT',
    packages=find_packages(include=('wkey', 'wkey.*')),
    entry_points={
        'console_scripts': [
            'wkey=wkey.wkey:main',
            'fkey=wkey.find_key:main',
            'wkey-tray=wkey.tray_app:main',
        ],
    },
    install_requires=required,
    include_package_data=True,
    zip_safe=False,
)
 

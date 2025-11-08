from setuptools import setup, find_packages

def readme():
    with open('README.md') as f:
        return f.read()


with open('README.rst') as f:
    long_description = f.read()

with open('requirements.txt') as f:
    required = f.read().splitlines()

setup(
    name='wkey',
    version='0.2',
    description='Integrate OpenAI speech-to-text Whisper with your keyboard',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/vlad-ds/whisper-keyboard',
    author='Vlad Gheorghe',
    author_email='vlad.datapro@gmail.com',
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
 

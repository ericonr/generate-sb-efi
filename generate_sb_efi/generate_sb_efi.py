#!/usr/bin/env python
# -*- coding: utf-8 -*-

# stdlib modules
import configparser, subprocess
from pathlib import Path
from shutil import copyfile
from typing import Dict, List

# external modules
import click


class SubprocessError(Exception):
    pass


def subrun(command: List[str], expected_return: int = 0, print_failure: bool = True):
    result = subprocess.run(command, capture_output=True)
    if result.returncode != expected_return:
        if print_failure:
            default_encoding = 'utf-8'
            print('==> Command:')
            print(command)
            print('==> Output:')
            print(result.stdout.decode(default_encoding))
            print('==> Error:')
            print(result.stderr.decode(default_encoding))

        raise SubprocessError(f'There was an error with the {command[0]} operation.')


class Kernel():
    '''Class that stores the parameters related to each kernel that will be
    used to build a single file EFI executable.
    '''
    def __init__(
            self,
            kernel_path: Path,
            config: Dict[str, str],
            key_prefix: str,
            initramfs_types: List[str] = ['', '-fallback']):
        '''Args:
        '''
        # Prefix of the kernel files
        self.prefix = config['prefix'] 
        # Command line used on the kernel
        self.cmdline = config['cmdline']

        # Key information and verification of permission
        self.key_path = Path(f'{key_prefix}.key')
        self.crt_path = Path(f'{key_prefix}.crt')

        # Optional files
        # Prefix of the initramfs files
        self.initramfs_prefix = config.get('initramfs')
        # Name of the microcode image
        self.ucode_name = config.get('ucode')

        # Optional flags
        # Define if the fallback image will be copied
        self.use_fallback = config.getboolean('use_fallback', False)
        # Defined if copies will also be copied to bootdir
        self.create_copy_bootdir = config.getboolean('create_copy_bootdir', False)

        # Retrieving kernel info
        self.path = kernel_path
        self.kernel_name = self.path.name

        # Types of initramfs images that will be used
        self.initramfs_types = initramfs_types

        # Folder where the copies of the images are kept
        self.copydir = Path(config['bootdir']) / 'signed-copy'

        self.extract_version()
        self.find_initramfs()


    def extract_version(self):
        '''Extract version info from the kernel file name.
        '''
        self.kernel_name = self.path.name
        self.version = self.kernel_name[len(self.prefix)::]


    def find_initramfs(self):
        '''Locate the initramfs file of each kernel, both normal and fallback.
        Locate the microcode as well.
        '''
        if self.initramfs_prefix is None:
            self.initramfs = None
        else:
            self.initramfs = {
                    suffix: self.path.parent / f'{self.initramfs_prefix}{self.version}{suffix}.img'
                    for suffix in self.initramfs_types
                    }
            for key in self.initramfs_types:
                if not self.initramfs[key].exists():
                    name = self.initramfs[key]
                    raise FileNotFoundError(f'Initramfs {name} doesn\'t exist.')

        if self.ucode_name is None:
            self.ucode = None
        else:
            self.ucode = self.path.parent / self.ucode_name
            if not self.ucode.exists():
                name = self.ucode
                raise FileNotFoundError(f'Microcode {name} doesn\'t exist.')


    def build(self, builddir: Path):
        '''Build and sign the kernel image.
        '''
        self.builddir = builddir / self.version
        self.builddir.mkdir(parents=True, exist_ok=True)

        # Create cmdline file
        with open(self.builddir / 'cmdline.txt', 'w') as cmdline_file:
            cmdline_file.write(self.cmdline + '\n')

        def extract_initramfs(initramfs_type: str):
            '''Extract the gzip compressed initramfs, and concatenate it with
            microcode.
            '''
            initramfs_path = self.initramfs[initramfs_type]

            with open(self.builddir / f'initramfs{initramfs_type}', 'wb') as initramfs_file:
                if self.initramfs_prefix is not None:
                    initramfs_content = subprocess.run(['zcat', initramfs_path], capture_output=True)
                    initramfs_file.write(initramfs_content.stdout)

                # Concatenate microcode with initramfs
                if self.ucode_name is not None:
                    with open(self.ucode, 'rb') as ucode_file:
                        initramfs_file.write(ucode_file.read())

        def assemble_single_file(initramfs_type: str):
            '''Assemble all files into a single image, and sign it.
            '''
            def add_section(section: str, file_name: Path, offset: str):
                return ['--add-section', f'{section}={file_name}',
                        '--change-section-vma', f'{section}={offset}'
                        ]

            sections = [('.osrel', Path('/etc/os-release'), '0x20000'),
                        ('.cmdline', self.builddir / 'cmdline.txt', '0x30000'),
                        ('.linux', self.path, '0x40000'),
                        ('.initrd', self.builddir / f'initramfs{initramfs_type}', '0x3000000')
                        ]

            sections_command = []
            for section in sections:
                sections_command += add_section(*section)

            self.target[initramfs_type] = Path(self.builddir / f'{self.kernel_name}{initramfs_type}')

            command = ['objcopy'] + sections_command + ['/usr/lib/systemd/boot/efi/linuxx64.efi.stub', self.target[initramfs_type]]
            subrun(command)

            self.result[initramfs_type] = Path(
                    self.target[initramfs_type].parent / f'{self.target[initramfs_type].name}.signed.efi'
                    )

            command = [
                'sbsign',
                '--key', self.key_path,
                '--cert', self.crt_path,
                '--output', self.result[initramfs_type],
                self.target[initramfs_type]
                ]
            subrun(command)

            print(f'Signed {self.result[initramfs_type].name}!')

        self.target = {}
        self.result = {}

        for initramfs_type in self.initramfs_types:
            extract_initramfs(initramfs_type)
            assemble_single_file(initramfs_type)


    def write(self, targetdir: Path):
        targetdir.mkdir(parents=True, exist_ok=True)

        if self.create_copy_bootdir:
            self.copydir.mkdir(parents=True, exist_ok=True)

        for initramfs_type in self.initramfs_types:
            if self.create_copy_bootdir:
                signed_name = f'{self.target[initramfs_type].name}.signed'
                copyfile(
                        self.result[initramfs_type],
                        self.copydir / signed_name
                        )
                print(f'Copied {signed_name} to {self.copydir}!')

            if 'fallback' in initramfs_type and not self.use_fallback:
                continue

            copyfile(
                    self.result[initramfs_type],
                    targetdir / self.target[initramfs_type].name
                    )
            print(f'Copied {self.target[initramfs_type].name}!')


@click.command()
@click.option('-c', '--conf', default='/etc/generate-sb-efi.conf', type=click.File('r'))
@click.option('--refind', is_flag=True, default=False)
@click.option('-d', '--dry-run', is_flag=True, default=False)
def cli(**kwargs):
    config = configparser.ConfigParser()
    config.read_file(kwargs['conf'])
    source_config = config['source']

    bootdir = Path(source_config['bootdir'])
    builddir = Path(config['artifacts']['builddir'])
    targetdir = Path(config['artifacts']['targetdir'])
    prefix = source_config['prefix']

    kernels = [Kernel(kernel, config=source_config, key_prefix=config['keys']['prefix']) for kernel in bootdir.glob(f'{prefix}*')]
    [kernel.build(builddir) for kernel in kernels]
    [kernel.write(targetdir) for kernel in kernels]

    if kwargs['refind']:
        refind_path = targetdir / 'refind_linux.conf'
        if not refind_path.exists():
            with open(refind_path, 'w') as refind_file:
                refind_file.write('"Boot"  ""')
            print(f'Wrote {refind_path}!')
        else:
            print(f'{refind_path} already exists!')


if __name__ == '__main__':
    cli()


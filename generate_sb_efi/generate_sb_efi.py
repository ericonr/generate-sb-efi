#!/usr/bin/env python
# -*- coding: utf-8 -*-

# stdlib modules
import configparser
from pathlib import Path
from shutil import copyfile
from pathlib import Path

# external modules
import subprocess
import click

class KernelException(Exception):
    pass


class Kernel():
    '''Class that stores the parameters related to each kernel that will be
    used to build a single file EFI executable.
    '''
    def __init__(self, kernel_path: Path, config: dict):
        '''Args:
        '''
        # Prefix of the kernel files
        self.prefix = config['prefix']
        # Prefix of the initramfs files
        self.initramfs_prefix = config['initramfs']
        # Name of the microcode image
        self.ucode_name = config['ucode']
        # Command line used on the kernel
        self.cmdline = config['cmdline']

        # Retrieving kernel info
        self.path = kernel_path
        self.kernel_name = self.path.name

        # Verify if kernel file has already been signed
        self.signed = 'signed' in self.kernel_name
        self.valid = (self.signed and config.getboolean('use_signed')) or not self.signed

        if self.valid:
            self.extract_version()
            self.find_initramfs()


    def extract_version(self):
        '''Extract version info from the kernel file name.
        '''
        self.kernel_name = self.path.name
        self.version = self.kernel_name[len(self.prefix)::]
        if self.signed:
            raise KernelException('Signed kernel handling not implemented yet')


    def find_initramfs(self):
        '''Locate the initramfs file of each kernel, both normal and fallback.
        Also microcode.
        '''
        self.initramfs = self.path.parent / f'{self.initramfs_prefix}{self.version}.img'
        if not self.initramfs.exists():
            raise FileNotFoundError('Initramfs doesn\'t exist.')

        self.initramfs_fallback = self.path.parent / f'{self.initramfs_prefix}{self.version}-fallback.img'
        if not self.initramfs_fallback.exists():
            raise FileNotFoundError('Fallback initramfs doesn\'t exist.')

        self.ucode = self.path.parent / self.ucode_name
        if not self.ucode.exists():
            raise FileNotFoundError('Microcode doesn\'t exist.')


    def build(self, builddir: Path):
        self.builddir = builddir / self.version
        self.builddir.mkdir(parents=True, exist_ok=True)

        # Create cmdline file
        with open(self.builddir / 'cmdline.txt', 'w') as cmdline_file:
            cmdline_file.write(self.cmdline + '\n')

        def extract_initramfs(initramfs, initramfs_name):
            '''Extract the gzip compressed initramfs, and concatenate it with
            microcode.
            '''
            with open(self.builddir / f'initramfs{initramfs_name}.img', 'wb') as initramfs_file:
                initramfs_content = subprocess.run(['zcat', initramfs], capture_output=True)
                initramfs_file.write(initramfs_content.stdout)

                # Concatenate microcode with initramfs
                with open(self.ucode, 'rb') as ucode_file:
                    initramfs_file.write(ucode_file.read())

        def assemble_single_file(initramfs_name):
            '''Assemble all files into a single image, and sign it.
            '''
            def add_section(section, file_name, offset):
                return ['--add-section', f'{section}={file_name}',
                        '--change-section-vma', f'{section}={offset}'
                        ]

            sections = [('.osrel', Path('/etc/os-release'), '0x20000'),
                        ('.cmdline', self.builddir / 'cmdline.txt', '0x30000'),
                        ('.linux', self.path, '0x40000'),
                        ('.initrd', self.builddir / f'initramfs{initramfs_name}.img', '0x3000000')
                        ]
            sections_command = []
            for section in sections:
                sections_command += add_section(*section)

            self.target[initramfs_name] = Path(str(self.builddir / f'{self.kernel_name}{initramfs_name}'))
            command = ['objcopy'] + sections_command + ['/usr/lib/systemd/boot/efi/linuxx64.efi.stub', self.target[initramfs_name]]
            objcopy_result = subprocess.run(command, capture_output=True)

            self.result[initramfs_name] = Path(f'{str(self.target[initramfs_name])}.signed.efi')
            sbsign_result = subprocess.run(['sbsign',
                                            '--key', '/etc/refind.d/keys/refind_local.key',
                                            '--cert', '/etc/refind.d/keys/refind_local.crt',
                                            '--output', self.result[initramfs_name],
                                            self.target[initramfs_name]
                                            ],
                                           capture_output=True)
            print(f'Signed {self.result[initramfs_name].name}!')

        self.target = {}
        self.result = {}

        extract_initramfs(self.initramfs, '')
        assemble_single_file('')
        extract_initramfs(self.initramfs_fallback, '-fallback')
        assemble_single_file('-fallback')


    def write(self, targetdir: Path):
        targetdir.mkdir(parents=True, exist_ok=True)
        for initramfs_name in self.result.keys():
            copyfile(self.result[initramfs_name], targetdir / self.target[initramfs_name].name)
            print(f'Copied {self.target[initramfs_name].name}!')


@click.command()
@click.option('-c', '--conf', default='/etc/generate-sb-efi.conf', type=click.File('r'))
@click.option('--refind', is_flag=True, default=False)
@click.option('-d', '--dry-run', is_flag=True, default=False)
def cli(**kwargs):
    config = configparser.ConfigParser()
    config.read_file(kwargs['conf'])
    source_config = config['source']

    bootdir = Path(source_config['bootdir'])
    builddir = Path(config['build']['builddir'])
    targetdir = Path(config['write']['targetdir'])
    prefix = source_config['prefix']

    kernels = [Kernel(kernel, config=source_config) for kernel in bootdir.glob(f'{prefix}*')]
    kernels = [kernel for kernel in kernels if kernel.valid]
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


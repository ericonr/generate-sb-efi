#!/usr/bin/env python

import subprocess
import click
import configparser
from pathlib import Path
from shutil import copyfile

class Kernel():
    def __init__(self, kernel_path: Path, config: dict):
        self.prefix = config['prefix']
        self.initramfs_prefix = config['initramfs']
        self.ucode_name = config['ucode']
        self.cmdline = config['cmdline']

        self.path = kernel_path
        self.kernel_name = self.path.name

        self.signed = 'signed' in self.kernel_name
        self.valid = (self.signed and config.getboolean('use_signed')) or not self.signed

        if self.valid:
            self.extract_version()
            self.find_initramfs()

    def extract_version(self):
        self.kernel_name = self.path.name
        self.version = self.kernel_name[len(self.prefix)::]
        if self.signed:
            raise Exception('Signed kernel handling not implemented yet')

    def find_initramfs(self):
        self.initramfs = self.path.parent / f'{self.initramfs_prefix}{self.version}.img'
        if not self.initramfs.exists():
            raise Exception('Initramfs doesn\'t exist.')

        self.initramfs_fallback = self.path.parent / f'{self.initramfs_prefix}{self.version}-fallback.img'
        if not self.initramfs_fallback.exists():
            raise Exception('Fallback initramfs doesn\'t exist.')

        self.ucode = self.path.parent / self.ucode_name
        if not self.ucode.exists():
            raise Exception('Microcode doesn\'t exist.')

    def build(self, builddir: Path):
        self.builddir = builddir / self.version
        self.builddir.mkdir(parents=True, exist_ok=True)

        with open(self.builddir / 'cmdline.txt', 'w') as cmdline_file:
            cmdline_file.write(self.cmdline + '\n')

        def extract_initramfs(initramfs, initramfs_name):
            with open(self.builddir / f'initramfs{initramfs_name}.img', 'wb') as initramfs_file:
                initramfs_content = subprocess.run(['zcat', initramfs], capture_output=True)
                initramfs_file.write(initramfs_content.stdout)
                with open(self.ucode, 'rb') as ucode_file:
                    initramfs_file.write(ucode_file.read())

        extract_initramfs(self.initramfs, '')
        extract_initramfs(self.initramfs_fallback, '-fallback')

        def add_section(section, file_name, offset):
            return ['--add-section', f'{section}={file_name}', '--change-section-vma', f'{section}={offset}']

        sections = [('.osrel', '/etc/os-release', '0x20000'),
                    ('.cmdline', f'{str(self.builddir / "cmdline.txt")}', '0x30000'),
                    ('.linux', str(self.path), '0x40000'),
                    ('.initrd', f'{str(self.builddir / "initramfs.img")}', '0x3000000')
                    ]
        sections_command = []
        for section in sections:
            sections_command += add_section(*section)

        self.target = Path(str(self.builddir / self.kernel_name))
        command = ['objcopy'] + sections_command + ['/usr/lib/systemd/boot/efi/linuxx64.efi.stub', str(self.target)]
        objcopy_result = subprocess.run(command, capture_output=True)
        print(command)
        print(objcopy_result.stdout, objcopy_result.stderr)

        self.result = f'{str(self.target)}.signed.efi'
        sbsign_result = subprocess.run(['sbsign', '--key', '/etc/refind.d/keys/refind_local.key', '--cert', '/etc/refind.d/keys/refind_local.crt', '--output', self.result, str(self.target)], capture_output=True)

    def write(self, targetdir: Path):
        targetdir.mkdir(parents=True, exist_ok=True)
        copyfile(self.result, targetdir / self.target.name)


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
        refind_path = targetdir / 'linux_refind.conf'
        print(refind_path)
        if not refind_path.exists():
            with open(refind_path, 'w') as refind_file:
                refind_file.write('"Boot"  ""')


if __name__ == '__main__':
    cli()

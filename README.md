# Automate generation of Secure Boot signed single file kernel images

## Motivation

If you are a user of boot managers like rEFInd, systemd-boot, or don't use any boot manager, you might be unable to boot directly from an encrypted partition. Because of this, you might find it necessary to leave your whole `/boot` partition unencrypted.

However, if the UEFI implementation on your device allows you to register your own Secure Boot keys and sign the kernel with them, you can, theoretically, guarantee that the kernel hasn't been tampered with. The issue with this approach, however, is that the initial ramdisk (`initramfs`), the processor microcode and the boot parameters are still prone to tampering, with no easy way to avoid said tampering. One of the slightly complicated ways of fixing this is to create a single EFI bootable image, which combines the kernel, information about the distro, boot parameters and the initial ramdisk into a single file that can then be signed with your own Secure Boot keys.

Unfortunately, this can quickly become a gargantuan task for maintenance, especially when using a distro which has several versions of the kernel installed at the same time. Therefore, automating the generation of these images becomes an interesting project.

## Configuration

Currently, configuration is done through the `/etc/generate-sb-efi.conf` file, which contains the configuration for the whole process of generating the signed kernel images. An example can be found inside `res/generate-sb-efi.conf`.

## External libraries

This program currently requires the click library for parsing command line arguments.


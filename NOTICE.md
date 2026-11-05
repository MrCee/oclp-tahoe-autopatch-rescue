# Upstream software

OCLP Tahoe USB Preparation for MacBookPro11,3 obtains official packages developed by Dortania and OpenCore Legacy Patcher contributors. Its optional experimental Recovery kit extracts additional runtime resources from those packages.

OCLP, OpenCore and their payloads are not distributed in this source repository. The preparation tool obtains or accepts the pinned official packages and stages them locally. Upstream copyrights and licenses continue to apply to those components; the MIT license here covers only this project's original custom code and documentation.

- [OpenCore Legacy Patcher](https://github.com/dortania/OpenCore-Legacy-Patcher)
- [OCLP license](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.3/LICENSE.txt)
- [Acidanthera OpenCorePkg](https://github.com/acidanthera/OpenCorePkg)
- [Matching KDK release](https://github.com/dortania/KdkSupportPkg/releases/tag/25G241)
- `oclp_board_ids.json` lists each model's board ID as published in [OCLP 3.0.0-rc.5 `smbios_data.py`](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/datasets/smbios_data.py).

Neither Dortania nor the upstream authors have endorsed this independent workflow. Apple's installer/KDK files are not relicensed by this repository. Personal logs and complete EFI folders are deliberately excluded.

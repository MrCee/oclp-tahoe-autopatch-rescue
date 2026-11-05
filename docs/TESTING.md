# Validation and limits

This is USB preparation automation, not a proven universal recovery fix. The manual hardware result and the public automated tests answer different questions. The optional custom Recovery helper is experimental.

## Physical-machine result and automation status

The owner confirmed a working Tahoe installation and completed user setup on a **mid-2014 MacBookPro11,3 only after erasing the internal drive again and reinstalling Tahoe from the fully modified USB**. KDK staging and repair attempts on the earlier installation had left it unusable. The public source preserves the recovery/staging logic, replaces the private USB identity with a creator-time binding, and uses the neutral service label `local.mbp113-repair`.

The automated launcher/staging checks below verify script behavior. They do not demonstrate that the script alone repaired the original installation, or that a clean reinstall is universally required.

**2026-10-17 owner-confirmed boot result:** the newly completed installation initially worked only through USB OpenCore. After installing OpenCore onto the internal drive and running `finish_install.py`, the owner reported that the MacBook booted successfully with the USB disconnected. This confirms the final handover on this one machine. The helper's own PASS remains configuration verification only; the subsequent physical boot was reported separately by the owner. Repeated restart qualification, performance, sleep/wake and GPU switching have not been independently verified.

The public packaging has not been run on a second physical Mac. There are no claimed performance, sleep/wake, GPU switching or future-update results. The sequence was not repeated with each dependency removed individually.

## Automated fixture checks

**2026-10-17 result:** all 109 checks passed on the preparation iMac, including internal-EFI handover, USB bundling and Command Line Tools bootstrap checks. Generated test output remains local and ignored.

Run on a working macOS development machine:

```bash
./scripts/test.sh
```

The script builds and ad-hoc signs the x86_64 native utility, checks the Bash scripts' syntax, and runs these suites:

| Suite | Checks | Method |
| :--- | ---: | :--- |
| Creator, EFI and native utility | 10 | Temporary files; mocked disk metadata; native XML/binary plist and SHA-256 operations |
| Optional Recovery preparation and EFI discovery | 19 | Disposable USB/EFI fixtures; package building mocked, native deployment hashes executed; no real disks |
| Default installer-only preparation and boot layout detection | 25 | Package/EFI fixtures and real Python deployment; automatic KDK image acquisition mocked; compiler/extraction prohibited; old-USB finishing bundle upgrade |
| Preparation prerequisites | 2 | Installer-only mode needs no compiler; optional mode reports absent compiler clearly |
| Autopatch Rescue (any model) | 18 | Fake installer USB and GitHub releases; no network or disk images. Covers adding both packages, skipping correct files, `--check` without writes, a replaced wrong package, corrupt and HTML-error downloads, missing digests, a missing KDK release and `--kdk-build`, an unsigned KDK, internal or non-installer volumes, pre-Big Sur installers, low space, and reading the OCLP tag |
| Download, copy progress and transfer integrity | 8 | Mocked responses; known/unknown sizes, scrolling bar, speed/ETA, large-file hash/copy progress, preserved copy metadata, truncated/corrupt transfers and interruption cleanup |
| Internal OpenCore config handover | 14 | Disposable EFI; disk/model/build commands mocked; no physical disk mounted or changed |
| USB finishing bundle and tools bootstrap | 13 | Bundled module imports, hashes, backups, reuse and symlink guards; fake Apple update/install commands; no real tools installed |
| Normal-boot startup job | 13 | Disposable filesystem; disk, patcher, power, signature and reboot commands stubbed |
| Recovery staging | 5 | Disposable System/Data/USB/EFI fixtures; destructive or hardware commands stubbed |

The checks cover correct patch completion, incomplete graphics output despite exit zero, patcher failure, prior attempt, wrong model/build/volume group, absent or incorrect USB, read-only installer logging to EFI, missing filesystem UUID, wrong filesystem, payload corruption, paired Data staging and rejection of symlinked deployment destinations.

The EFI tests verify that only the three documented DataHub fields change by default, that the source object remains unchanged, that an explicit normal-boot request removes only `-x`, and that a conflicting model is rejected. The native checks cover nested arrays, Unicode, booleans, integers, XML/binary plists, stdin, missing keys, valid/corrupted manifests and path traversal rejection.

The optional Recovery preparation checks exercise a fresh kit, incomplete kit repair with backups, reuse and idempotence, normal-boot NVRAM replacement, audit-only operation without file/mode changes, permission repair, same-USB EFI discovery and read-only mounting. They also reject missing enabled kexts, conflicting models, an internal/wrong EFI, nested backup configs, symlink destinations, corrupt/duplicate manifests, download caches on the USB, and disk/config changes during preparation. The package-builder subprocess is replaced with tiny fixtures in these orchestration tests; actual extraction/layout is covered by the real-package check below.

The default installer-only checks verify that only the two pinned packages and scoped EFI settings are prepared; no Recovery archive, helper or daemon is created. They cover local and downloaded packages, read-only KDK mounting and detachment, repair with backups, repeat runs, audit-only operation, and preservation of old optional kit files. Tests fail if package expansion or compilation is invoked by the installer-only builder. Additional checks cover Apple-only, UEFI and combined boot layouts, genuinely missing or empty bootstraps, symlink rejection, read-only EFI remounting without force, busy mounts, changed EFI identities, cleaned-up write probes, and actionable failure reports before downloads. Fresh missing packages now produce a normal preparation status rather than an exception-looking message, while retaining the detailed reason in the private report. Download tests verify progress formatting and cleanup without accessing the network. The default audit checks packages and EFI, while `--with-recovery-kit --check` also requires the optional kit.

Internal handover checks follow a simulated running APFS system to a physical disk other than `disk0`, verify config backups and scoped fixes, and distinguish configuration PASS from USB-free boot success. They cover repeat runs, audit-only and read-only mounting, wrong host/build/model, external or ambiguous storage, missing/unidentified EFI, absent OpenCore/bootstrap, symlinks, read-only write refusal and changed disk identity. An actual `finish_install.py --check` invocation on the preparation iMac also refused the wrong host before disk discovery or mounting. These checks do not install OCLP, change boot defaults or demonstrate a hardware restart.

The USB now carries the unchanged, owner-tested Python EFI helper together with its dependencies and a Bash launcher. Bundle tests verify that it imports without a repository checkout or third-party Python packages, stays below 200 KB, preserves old files/logs, repairs permissions and rejects corruption/symlinks. Bootstrap fixtures verify numeric Xcode-version selection (including 26.10 versus 26.9), reuse of existing Python, exact stable Command Line Tools selection, exclusion of macOS/beta updates, log creation, discovery/install failures and temporary-marker cleanup without deleting a preexisting marker. Apple update/install commands are replaced with disposable stubs: automatic tools acquisition still needs a fresh MacBook hardware test. Running the real launcher on the preparation iMac refused the wrong host before elevation, downloading or EFI writes.

The eight-file finishing bundle (about 70 KB) was also copied onto the owner's mounted installer USB. The full USB audit then passed: both pinned package hashes, bundled source/manifest/permissions, OpenCore references and model/normal-boot settings. The existing USB EFI config remained byte-for-byte unchanged during that bundle-only upgrade. The launcher has not been used to install developer tools on the MacBook in this new packaging route.

**These fixtures do not invoke OCLP or root-patch the development Mac.** Stubbing signature and disk commands allows testing the orchestration; it does not replace signature verification and real disk validation during actual preparation.

## Real-package assembly and live boot-file checks

**2026-10-16 result:** assembly and the complete generated manifest passed using the pinned official packages. The download asset hashes were also compared with GitHub's release-asset digests.

On 2026-10-17 the payload verifier also accepted that existing real-package assembly without changing its files. The simplified installer-only builder then copied the actual pinned assets/KDK packages into a disposable host output, deployed them into another disposable host directory and verified both hashes. Extraction and compilation were prohibited during that check. It passed with exactly the two expected package files and no Recovery files; no physical USB was changed.

The public builder is also checked against the actual pinned RC3 assets package and matching Apple KDK package: expand both, verify the RC3 app signature and version, merge the KDK SDK payload, compile the utility, generate the runtime/KDK archives and verify the resulting complete manifest.

This check uses a disposable test partition identifier and a host output directory. It does not deploy to a USB, modify the host EFI, run package installation scripts or patch an installed OS.

## What remains outside these tests

- Live download availability and macOS disk metadata can change; checksums/build guards deliberately fail closed.
- A different macOS build, OCLP revision, model or graphics configuration needs separate review.
- The fixture files contain placeholders in place of actual app/kernel binaries. Only the real-package assembly check validates the authentic payload layout.
- A correct package manifest does not prove a future boot or root patch will succeed. Inspect the generated logs and verify a working user session.

On 2026-10-17, read-only inspection of the owner's freshly created physical USB confirmed the RC3 Apple bootstrap layout at `System/Library/CoreServices/boot.efi`, a MacBookPro11,3 config and all referenced OpenCore files. The corrected preflight accepted that layout without copying or relocating any loader. Both installer-package hashes were subsequently verified on the mounted USB. The owner reported a completed installation initially usable only through the USB, then confirmed a USB-free boot after the internal OpenCore installation and `finish_install.py` step described above.

No private machine identifiers or raw owner logs are used as public test fixtures.

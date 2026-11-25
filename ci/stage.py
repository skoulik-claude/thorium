#!/usr/bin/env python3
"""One stage of the chained Windows build of Thorium on GitHub Actions.

Subcommands, run in this order across jobs:

  prepare   fetch Chromium at Thorium's version, apply Thorium and our
            patches, configure out/thorium (first stage only)
  build     run Ninja until done or until a deadline; exit 124 when the
            deadline stopped it, so the workflow saves the tree for the next
            stage
  package   turn the mini installer into the release files
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

WORK = Path(os.environ.get("THORIUM_CI_WORK", r"C:\b"))
SRC = WORK / "src"
OUT = SRC / "out" / "thorium"
DEPOT_TOOLS = WORK / "depot_tools"
DIST = WORK / "dist"
THORIUM = Path(__file__).resolve().parent.parent
PATCHES = THORIUM / "ci" / "patches"
ARGS_SOURCE = THORIUM / "other" / "AVX2" / "win_AVX2_args.gn"
SEVEN_ZIP = Path(r"C:\Program Files\7-Zip\7z.exe")

DEPOT_TOOLS_URL = "https://chromium.googlesource.com/chromium/tools/depot_tools.git"
CHROMIUM_URL = "https://chromium.googlesource.com/chromium/src.git"
BUILD_PHASES = (["thorium_all"], ["thorium_installer"])
DEADLINE_EXIT = 124

# GN arguments changed from Thorium's AVX2 Windows set, and why.
GN_OVERRIDES = {
    # Google's Widevine CDM may not be redistributed; DRM is not needed.
    "bundle_widevine_cdm": "false",
    # Ninja, not Siso: Ninja stops cleanly on Ctrl-Break, which the stage
    # deadline relies on.
    "use_siso": "false",
}


def log(message: str) -> None:
    print(f"[stage] {message}", flush=True)


def run(command: list[str | Path], cwd: Path | None = None) -> None:
    printable = subprocess.list2cmdline([str(part) for part in command])
    log(f"{cwd or Path.cwd()}> {printable}")
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def thorium_version() -> str:
    text = (THORIUM / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^THORIUM_VERSION = "([0-9.]+)"', text, re.MULTILINE)
    if not match:
        sys.exit("cannot read THORIUM_VERSION from version.py")
    return match.group(1)


VS2026 = Path(r"C:\Program Files\Microsoft Visual Studio\18\Enterprise")


def build_environment(update_depot_tools: bool = False) -> None:
    # Use the installed Visual Studio, not Google's internal toolchain package.
    os.environ["DEPOT_TOOLS_WIN_TOOLCHAIN"] = "0"
    if VS2026.is_dir():
        os.environ["vs2026_install"] = str(VS2026)
    # depot_tools updates and bootstraps its own Python on first use; after
    # that, every stage must use the same copy (it travels in the saved tree).
    os.environ["DEPOT_TOOLS_UPDATE"] = "1" if update_depot_tools else "0"
    os.environ["PATH"] = str(DEPOT_TOOLS) + os.pathsep + os.environ["PATH"]


def gclient() -> list[str]:
    return ["cmd", "/c", str(DEPOT_TOOLS / "gclient.bat")]


def write_args() -> None:
    lines = ARGS_SOURCE.read_text(encoding="utf-8").splitlines()
    seen = set()
    result = []
    for line in lines:
        name = line.split("=", 1)[0].strip()
        if name in GN_OVERRIDES:
            line = f"{name} = {GN_OVERRIDES[name]}"
            seen.add(name)
        result.append(line)
    result += [f"{name} = {value}" for name, value in GN_OVERRIDES.items()
               if name not in seen]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "args.gn").write_text("\n".join(result) + "\n", encoding="utf-8")
    log("args.gn:\n" + "\n".join(result))


def prepare(_: argparse.Namespace) -> None:
    version = thorium_version()
    log(f"Thorium {version}")
    WORK.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--depth=1", DEPOT_TOOLS_URL, DEPOT_TOOLS])
    build_environment(update_depot_tools=True)
    run(gclient() + ["--version"], cwd=WORK)  # bootstraps python3 and friends
    build_environment()
    (WORK / ".gclient").write_text(
        "solutions = [{\n"
        '  "name": "src",\n'
        f'  "url": "{CHROMIUM_URL}",\n'
        '  "managed": False,\n'
        '  "custom_deps": {},\n'
        '  "custom_vars": {"checkout_pgo_profiles": True},\n'
        "}]\n"
        'target_os = ["win"]\n',
        encoding="utf-8",
    )
    # Shallow, at the tag Thorium is based on: version.py needs full history
    # to check out a tag, which a CI disk cannot hold.
    run(gclient() + ["sync", "--revision", f"src@refs/tags/{version}",
                     "--no-history", "--shallow", "--nohooks", "--jobs=8"],
        cwd=WORK)
    run(gclient() + ["runhooks"], cwd=WORK)
    run([sys.executable, THORIUM / "setup.py", "--avx2",
         f"--chromium-src={SRC}", f"--thorium-root={THORIUM}"], cwd=THORIUM)
    for patch in sorted(PATCHES.glob("*.patch")):
        run(["git", "apply", "--verbose", patch], cwd=SRC)
    write_args()
    run([SRC / "buildtools" / "win" / "gn.exe", "gen", OUT], cwd=SRC)
    disk_report()


def disk_report() -> None:
    for drive in ("C:\\", "D:\\"):
        if Path(drive).exists():
            usage = shutil.disk_usage(drive)
            log(f"{drive} free {usage.free / 2**30:.0f} of "
                f"{usage.total / 2**30:.0f} GiB")


def build(args: argparse.Namespace) -> int:
    build_environment()
    ninja = SRC / "third_party" / "ninja" / "ninja.exe"
    environment = dict(os.environ, NINJA_STATUS="[%f/%t %es] ")
    for targets in BUILD_PHASES:
        remaining = args.deadline - time.time()
        if remaining < 60:
            log("deadline reached before the next phase")
            return DEADLINE_EXIT
        command = [str(ninja), "-C", str(OUT), "-j", str(args.jobs), *targets]
        log(f"{subprocess.list2cmdline(command)} "
            f"(up to {remaining / 60:.0f} min)")
        process = subprocess.Popen(
            command, cwd=SRC, env=environment,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            # Ctrl-Break makes Ninja stop its jobs and delete their partial
            # outputs, so the next stage resumes from a consistent tree.
            log("deadline: sending Ctrl-Break to Ninja")
            process.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                log("Ninja did not stop; killing it")
                subprocess.run(["taskkill", "/T", "/F", "/PID",
                                str(process.pid)])
                process.wait()
            disk_report()
            return DEADLINE_EXIT
        if returncode != 0:
            log(f"Ninja failed with exit code {returncode}")
            return returncode
    disk_report()
    return 0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def package(_: argparse.Namespace) -> None:
    version = thorium_version()
    installers = sorted(OUT.glob("*mini_installer*.exe"))
    if len(installers) != 1:
        sys.exit(f"expected one mini installer in {OUT}, found {installers}")
    DIST.mkdir(parents=True, exist_ok=True)
    installer = DIST / f"Thorium_AVX2_{version}_mini_installer.exe"
    shutil.copy2(installers[0], installer)
    portable = DIST / f"Thorium_AVX2_{version}_portable.zip"
    run([sys.executable, THORIUM / "infra" / "portable" / "portable.py",
         "--platform", "windows", "--input", installers[0],
         "--seven-zip", SEVEN_ZIP, "--expected-version", version,
         "--output", portable])
    sums = [f"{sha256(path)} *{path.name}" for path in (installer, portable)]
    (DIST / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n",
                                         encoding="utf-8")
    (DIST / "VERSION").write_text(version + "\n", encoding="utf-8")
    log("\n".join(sums))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare").set_defaults(handler=prepare)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--deadline", type=float, required=True,
                              help="Unix time at which to stop Ninja")
    build_parser.add_argument("--jobs", type=int, default=4)
    build_parser.set_defaults(handler=build)
    commands.add_parser("package").set_defaults(handler=package)
    args = parser.parse_args()
    return args.handler(args) or 0


if __name__ == "__main__":
    sys.exit(main())

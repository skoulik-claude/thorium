# Thorium for Windows, built in GitHub Actions — plan

*2026-11-25. Agreed.*

## Why

Thorium's last non-beta Windows release is 138 (February 2026). Newer Thorium exists only as
gz83's M144–M158 betas, and the M158 Windows build does not work on our target desktop
(Windows 10 22H2, a third-party antivirus): every sandboxed renderer exits `0xC0000428`
because Windows Code Integrity refuses the unsigned `chrome_elf.dll` (event 3033). Chromium
158 enforces "Microsoft-signed DLLs only" on renderers unconditionally and lets Chrome's own
DLLs through by an allow-list (`AllowExtraDll`), which fails on that machine; Chromium 138
applied the rule only behind a flag, which is why Thorium 138 works. Why the allow-list fails
is open: the antivirus's hooks, or the beta being cross-compiled for Windows on Linux.

Building it natively answers that, and gives a build whose provenance is public: source
pinned by commit, every step in a public log. Not a local build: it would occupy a shared
desktop for 5–10 h per build and need installs on it.

## What

A public fork, **`skoulik-claude/thorium`** (created 2026-11-25), so that following upstream
is a fast-forward:

- **`main`** mirrors `Alex313031/thorium` and only ever fast-forwards. It starts at `b2882865`
  (2026-11-20: Thorium **158.0.8127.41**, the version of the failing beta).
- **`ci`** is `main` plus our commits — the workflow and the scripts it runs under `ci/`, our
  patches under `ci/patches/` (applied by the workflow after Thorium's own, so upstream files
  stay untouched), this plan — and is the fork's **default branch**, which
  `workflow_dispatch` needs. On a Thorium update: fast-forward `main`, rebase `ci` onto it.

GitHub silently throttles forks whose workflows use Actions heavily. Upstream's five
workflows are all manual-only (`workflow_dispatch` / `workflow_call`), so none runs by
itself; still, Actions stays **off** on the fork until our workflow is ready, and when it is
switched on the five are disabled one by one.

## How the build runs

GitHub's free Windows runners (public repositories only) have 4 cores, 16 GB RAM, and a
6-hour limit per job; a Chromium official build needs far more. ungoogled-chromium-windows
(BSD-3) solves this with **chained stages** — each job builds for a fixed time, saves the
tree as an artifact, and the next job resumes — and finishes Chromium 158 in 8–40 h of wall
time. We copy that pattern.

1. **Prepare** (first job): install Windows SDK 10.0.28000 (Chromium 158 pins it; the runner
   has 10.0.26100) as ungoogled-chromium does; use the runner's VS 2022 (accepted by
   `build/vs_toolchain.py`); `DEPOT_TOOLS_WIN_TOOLCHAIN=0`. Clone depot_tools, check out `ci`
   with its submodules, then Thorium's own scripts: `get_repo.py --no-history`, `version.py`,
   `setup.py --avx2`; apply our patches; `gn gen` with Thorium's `win_args.gn`, the AVX2
   profile and our overrides (below). Log free disk and RAM.
2. **Build stages** (jobs 2…N): restore the tree, build with a time budget that leaves room
   to archive and upload, save the tree (without `.git`) as an artifact (`retention-days: 1`),
   hand over. The tree stays at the same absolute path in every stage.
3. **Package**: `mini_installer` and a portable zip, SHA-256 of each, published as a
   **GitHub Release** tagged with the Thorium version and our revision; the release notes link
   the run.

Re-running for a Thorium update means fast-forwarding `main`, rebasing `ci` and starting the
workflow.

### GN overrides

- `bundle_widevine_cdm = false`. Thorium's repository carries Google's Widevine CDM, whose
  licence forbids redistribution; a public release must not bundle it. DRM playback is not
  needed, so it is not tested.

## Our patch

One, kept small: make the renderer's start-up code integrity honour the existing
`--allow-third-party-modules` switch, as it already does for the WebNN process
(`ChromeContentBrowserClient::PreSpawnChild`). Default behaviour stays upstream's. If
renderers still die on the target machine, launching with the switch restores what Thorium
138 does; if they live, the cross-compile was the cause.

It is **its own commit on `ci`**, the message saying what it changes and why, so it can be
dropped, or offered upstream, on its own.

## Testing

On the target desktop, as for the beta: the portable zip under `%LOCALAPPDATA%`, a throw-away
profile, profile encryption on. Pass means renderers alive (exit codes watched, no Code
Integrity 3033 events) and code.qt.io loading; then, by hand, Google sign-in and sync, and an
MV2 extension running.

## Risks

- **Runner disk.** A `--no-history` checkout plus an official build's `out` is large; the
  first job measures it. Fallback: trim with Thorium's `--nohooks` paths and `target_os`.
- **Artifact size and transfer time** per stage eat into the 6-hour window.
- **Memory.** ThinLTO's final link of `chrome.dll` on 16 GB: ungoogled-chromium manages, at
  `-j 2`.
- **Debug cycle.** A failure in a late stage costs hours of wall time; stages log enough to
  fix it from the log.

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

1. **Prepare** (first stage): clone and bootstrap depot_tools; fetch Chromium with `gclient
   sync` **shallow, at the tag `version.py` names** (Thorium's `get_repo.py` + `version.py`
   check the tag out of a full-history clone, which a runner's disk cannot hold); `gclient
   runhooks`; Thorium's `setup.py --avx2`; our patches; `gn gen`. Logs free disk.
2. **Build** (every stage): Ninja until done or until 280 minutes into the job, then
   Ctrl-Break — Ninja stops its jobs and deletes their partial outputs — and the tree
   (`src`, depot_tools, without `.git`) goes into a 7z archive, which keeps the 100 ns file
   times Ninja's checks need, uploaded for the next stage. The last stage saves its finished
   tree as well, and every saved tree is kept 21 days, so that a problem found in the first
   weeks of use is fixed by resuming rather than by a full rebuild; `ci-keep-state.yml`
   copies an older run's tree to keep it longer, since GitHub cannot extend an
   artifact's retention. Every stage
   uses the same absolute path, `D:\b` — the runner's 150 GB temporary disk, since `C:` has
   only about 30 GB free (measured 2026-11-25). Twelve stages at most; a run can resume another
   run's saved tree (`resume-run`), for fixing a failure without starting over.
3. **Package**: Chromium's **mini installer** (agreed; it updates an existing per-user
   Thorium in place) and Thorium's own portable zip (`infra/portable/portable.py`), SHA-256
   of each, published as a **GitHub pre-release** tagged with the Thorium version and run
   number; the release notes link the run and commit. Publishing lives in `ci-release.yml`,
   which takes a build run's ID. **The tag is pushed by hand first**
   (`thorium-<version>-avx2-ci<run number>` on the build's commit): GitHub refuses the
   workflow token a tag on a commit holding workflow files (it wants `workflows=write`,
   which `GITHUB_TOKEN` never has), so the build's own release job fails until the tag
   exists, and `ci-release.yml` is then run for that build.

Re-running for a Thorium update means fast-forwarding `main`, rebasing `ci` and starting the
workflow.

### OS and toolchain

- **Runner `windows-2025-vs2026`** (agreed), by that label rather than `windows-latest`:
  Windows Server 2025 with **Visual Studio 2026** Enterprise 18.12 and ATL/MFC — what
  Chromium 158's build guide requires. Fallback: `windows-2022` with VS 2022, which
  `build/vs_toolchain.py` also accepts and ungoogled-chromium builds 158 with.
- **Windows SDK 10.0.28000** installed in every stage (pinned in `build/vs_toolchain.py`;
  neither image has it), as ungoogled-chromium does.
- **Compiler, linker, Rust**: Chromium's own pinned clang, lld and Rust, fetched by
  `gclient runhooks`; nothing else is supported.
- **Ninja**, not Siso (`use_siso = false`): its Ctrl-Break behaviour is what the stage
  deadline relies on. Python 3.12 for the scripts; depot_tools' own Python for the build.
- Not cross-compiled on Linux: that is how the failing beta was built.

### GN overrides

On top of Thorium's `other/AVX2/win_AVX2_args.gn`:

- `bundle_widevine_cdm = false`. Thorium's repository carries Google's Widevine CDM, whose
  licence forbids redistribution; a public release must not bundle it. DRM playback is not
  needed, so it is not tested.
- `use_siso = false` (above).

## Our patch

One, kept small: make the renderer's start-up code integrity honour the existing
`--allow-third-party-modules` switch, as it already does for the WebNN process
(`ChromeContentBrowserClient::PreSpawnChild`). Default behaviour stays upstream's. If
renderers still die on the target machine, launching with the switch restores what Thorium
138 does; if they live, the cross-compile was the cause.

It is **its own commit on `ci`**, the message saying what it changes and why, so it can be
dropped, or offered upstream, on its own.

Thorium's own `--disable-direct-write` (`#force-gdi`) also lifts that rule — it makes the beta
work on the target machine (checked 2026-11-25) — but it switches text to GDI and relaxes
more of the sandbox (win32k lockdown, non-system fonts, dynamic code in the browser). **The
build keeps DirectWrite**; the switch above is the narrower way out.

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

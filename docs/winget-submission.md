# Submitting TokenWatcher to winget

Once a manifest is merged into [`microsoft/winget-pkgs`](https://github.com/microsoft/winget-pkgs), users can install with:

```powershell
winget install gehariharan.TokenWatcher
```

This bypasses Edge SmartScreen download warnings entirely.

## One-time submission (v0.1.0)

The manifests are already prepared in `winget/0.1.0/` of this repo with the correct SHA-256 hash for the released installer.

### Steps

1. **Fork** [`microsoft/winget-pkgs`](https://github.com/microsoft/winget-pkgs) on GitHub.

2. **Clone your fork** locally:
   ```powershell
   git clone git@github.com:gehariharan/winget-pkgs.git
   cd winget-pkgs
   ```

3. **Copy the manifests** into the right place:
   ```powershell
   $dest = "manifests\g\gehariharan\TokenWatcher\0.1.0"
   New-Item -ItemType Directory -Force -Path $dest
   Copy-Item "..\Tokenwatcher\winget\0.1.0\*.yaml" $dest
   ```

4. **(Optional) Validate locally** to catch problems before pushing:
   ```powershell
   winget validate --manifest manifests\g\gehariharan\TokenWatcher\0.1.0
   ```

5. **Test the install locally** (winget needs the dev / pre-release version of itself for sandbox testing):
   ```powershell
   winget install --manifest manifests\g\gehariharan\TokenWatcher\0.1.0
   ```

6. **Commit + push to a branch on your fork**:
   ```powershell
   git checkout -b add-tokenwatcher-0.1.0
   git add manifests/g/gehariharan/TokenWatcher/0.1.0
   git commit -m "New package: gehariharan.TokenWatcher version 0.1.0"
   git push -u origin add-tokenwatcher-0.1.0
   ```

7. **Open a PR** to `microsoft/winget-pkgs:master`. The PR template will show automatically. The Microsoft validation bot runs automatic checks within minutes; a human reviewer typically merges in 1–3 days.

## Updating for future releases

When you cut a new version (e.g. `v0.2.0`):

1. Run `scripts\bump-winget-manifest.ps1 -Version 0.2.0` (or update by hand) — this re-downloads the new installer, computes SHA-256, and writes a new `winget\0.2.0\` directory.
2. Repeat the fork → copy → PR steps above.

Or use [`vedantmgoyal2009/winget-releaser`](https://github.com/vedantmgoyal2009/winget-releaser), a GitHub Action that auto-opens the winget PR whenever you publish a GitHub Release. Add it to `.github/workflows/release.yml` once `v0.1.0` is merged.

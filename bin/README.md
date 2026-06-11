# NSSM package layout

Place the Windows NSSM binary here so the bootstrap can run without internet access.
You can also drop a local ZIP package here; the installer will extract it automatically.

Expected layout:

```text
bin/
  nssm/
    win32/
      nssm.exe
    win64/
      nssm.exe
```

The installer will look for `nssm.exe` under `bin/`, `bin/nssm/`, or any nested `win32` / `win64` folder and will copy or extract the local package into `C:\ProgramData\LLMBridge\bin\` during bootstrap.
It also accepts a ZIP file in `bin/` or `bin/nssm/`, or one passed through `-NssmPath` / `-NssmRoot`, if you want to keep the package compressed in your own workflow.

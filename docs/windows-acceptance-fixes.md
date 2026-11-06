# Windows acceptance repair goals

1. Deploy the already verified VAD assets to the normal per-user model directory;
   verify default startup without test environment overrides. Correct missing-model
   guidance for the offline installer.
2. Restore settings inside the monitor work area after the window manager finishes
   applying saved geometry; verify close/reopen after dragging below the screen.
3. Use F8 for start/stop in both subtitle and settings windows, avoiding the common
   Ctrl+Space input-method conflict. Retain Ctrl+Space as a compatibility binding.
4. Run regression tests, build a new CPU executable with provenance, and repeat
   Windows UI acceptance. Keep the previous distribution for rollback and preserve
   all previously denied cleanup items. No new download is needed.

Status: all four goals completed. The frozen executable built from source commit
`9536f358fea65e366ed9ad732286edfd2a451a96` passed direct default-environment
startup/model loading, F8 start/stop/cancel, and offscreen settings recovery using
Windows Computer Use. Regression coverage: 688 unit tests plus the separately
run Torch test passed. Detailed evidence and exclusions are under
`output/verification/windows-fixes-20261107/report.md`. No new installer or GitHub
push was performed. The denied temporary-file cleanup is appended to
`reliability-roadmap.md`; all rejected files are retained.

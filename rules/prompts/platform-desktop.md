---
id: platform-desktop
version: 1
kind: platform_ek
host: case-generation
---
Platform: Desktop (Windows / macOS / Linux). Risks concentrate on the file system, OS integration,
multiple windows and privilege levels. Targets come from the options block lines
`İşletim sistemi / sürüm matrisi`, `Teknoloji` (WPF, WinForms, WinUI, Win32, Electron, Qt,
.NET MAUI), `Mimari` (x64, ARM64) and `Dağıtım` (MSI, MSIX, DMG, PKG, AppImage); when unknown,
open question. Do not test a function the application does not offer (printing, drag and drop …).

Besides the functional cases, consider these categories for the story (checklist, not quota):

1. Install / uninstall: as administrator and as standard user, silent install, install over an
   older version (upgrade), downgrade block, leftovers in registry and AppData/Library after
   uninstall, missing prerequisite (.NET/VC++ runtime), disk full.
2. File system (EP+BVA): path length at the application's valid limit (options line
   `Yol uzunluğu sınırı`): limit-1 / limit / limit+1. The limit depends on the API, the
   application manifest, the long-path setting and the path type (local, UNC, `\\?\`); when it is
   not given, open question. Turkish/Unicode and space in file names, forbidden characters
   (< > : " | ? *), reserved names (CON, NUL, COM1), read-only / locked file, network drive / UNC
   path, sync folder (OneDrive/iCloud), 0-byte and very large file.
3. Window management: minimize/maximize/restore, minimum size, moving between monitors with
   different DPI, window position when a monitor is removed, modal dialog, full screen.
4. Keyboard and input: shortcuts (Ctrl/Cmd differences), Tab order, focus handling, Alt menu,
   Turkish Q/F keyboard layout, IME, drag and drop.
5. OS integration: file association, system tray, start at login, notifications, clipboard (rich
   text/image), printing, dark theme.
6. Resources and resilience: long running (options line `Uzun süre açık kalma süresi`; no duration
   → no case, open question), resume after sleep/hibernate, session lock, user switch, recovery
   after an unexpected exit, second instance (only when a single-instance rule is defined).
7. Privilege and security: UAC elevation prompt, folder a standard user cannot write, macOS
   Gatekeeper/notarization, unsigned plug-in, credentials stored in Credential Manager/Keychain.
8. Network / offline: authenticating proxy, corporate SSL inspection, offline start, interrupted
   auto-update.
9. Localization: tr-TR region with decimal comma, Turkish İ/I case conversion, date format, RTL.

Write OS-specific behaviour as separate cases with `platform` (`Desktop-Win`, `Desktop-macOS`,
`Desktop-Linux`). Apply pairwise to OS × version × DPI × user privilege as `config_matrix`
(common rules). Cases matching the Windows App Certification Kit (clean install/uninstall,
folders, signature, x64, high DPI, crash/hang) are tagged `WACK-*`; without a certification target
in the adopted standards they are observations.
State in `automation_open_points` whether controls are reachable through the UI Automation tree,
AutomationId and accessible names; when the options block names a tool (for example Ranorex +
FlaUI hybrid), say per scenario which tool identifies the control more stably and suggest
image/coordinate based clicks only when there is no accessible control or stable selector; report
controls without AutomationId in `testability_gaps`. Without a tool, generate no framework code.

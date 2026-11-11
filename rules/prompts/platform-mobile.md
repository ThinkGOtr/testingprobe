---
id: platform-mobile
version: 1
kind: platform_ek
host: case-generation
---
Platform: Mobile (iOS / Android). Most mobile defects appear at interruptions, network changes,
permissions and lifecycle transitions, so focus on state transitions and recovery. Targets come
from the options block lines `İşletim sistemi / sürüm matrisi`, `Cihaz sınıfları` and
`Uygulama tipi` (native, hybrid, Flutter, React Native, mobile web); when unknown, open question.

Besides the functional cases, consider these categories for the story (checklist, not quota):

1. App lifecycle (ST): foreground → background → foreground, app killed by the OS and reopened,
   screen lock/sleep and return, switching apps. At each transition: is entered data kept, is an
   operation repeated (double payment)?
2. Interruptions: incoming call, SMS, another app's push, alarm, low battery warning, headset or
   Bluetooth plug/unplug. Focus on RECOVERY: where does the flow continue afterwards?
3. Network: Wi-Fi ↔ mobile data during an operation, airplane mode, weak signal, action while
   offline and sync when online again, captive portal.
4. Permissions (DT): allow / deny / "don't ask again" / only while using / revoked later in
   settings. Is the permission asked at first need? Is there an alternative path when denied?
   (camera, location, notifications, contacts, files, biometrics)
5. Device state (BVA): storage full / limit-1 MB, low RAM, low battery / power saving, time zone or
   manual clock change, system language and font size (smallest / largest). Limits only from the
   source.
6. Screen and interaction: portrait ↔ landscape (data loss), no rotation when portrait-only,
   notch/dynamic island, foldable open/close, dark mode, gestures, fields visible with the keyboard
   open, Android back button.
7. Install and update: clean install, update from an older version (data migration), forced update
   screen, uninstall and reinstall (keychain/token leftovers), unsupported OS.
8. Notifications and deep links: tapping a push when the app is closed / in background / open, a
   deep link with an expired session, a deep link with invalid parameters.
9. Security (OWASP MASVS): sensitive data in screenshots/app switcher, rooted/jailbroken device,
   clipboard, local storage, logging, network transport. Attempt limits are boundary values only
   when the story defines them. Tag with the MASVS category and, when the options block gives
   one, the MAS profile (for example `MASVS-STORAGE-1`).
10. Accessibility: VoiceOver / TalkBack, Dynamic Type / font scaling. Touch target sizes (Apple HIG
    44×44 pt, Android Core App Quality 48 dp), 2 s start-up progress indicator and 16 ms frames are
    platform GUIDELINE targets: expected result only when the product adopted them (adopted
    standards line), otherwise an observation (`HIG-HitTarget`, `T-App_Startup_Time` …).

When iOS and Android behave differently, write separate cases and fill `platform`
(`Mobil-iOS` / `Mobil-Android`). Cases that an emulator cannot verify (camera, sensors, real
cellular network, battery) get `requires_real_device: true`.
Without an automation tool in the options block (Appium, Espresso, XCUITest, Maestro), invent no
code and no accessibility id.

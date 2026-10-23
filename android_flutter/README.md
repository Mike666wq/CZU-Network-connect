# Android Flutter application

Android version **0.5.0+2** embeds the shared Python core **0.4.2** through
Chaquopy. Flutter provides the interface; Kotlin provides Android networking,
foreground service and alarm integration. The shared `campus_assistant` sources
remain the source of truth for portal detection, authentication and scheduling.

This is a **debug test build**, not a production release. CI verifies APK
signature integrity using its debug key. That key is not a stable release
identity and can change between jobs or runs; installing over an older build
with a different key may require uninstalling it first, which removes app data.

## Build and download on GitHub

No local Flutter, Android SDK, Java, Chaquopy or Python installation is required
to obtain the APK. Push the Android integration branch, open the repository's
**Actions > Android Flutter CI and debug APK** run, and download its artifacts
after the checks finish.

- Pushes to `main` and `codex/**` trigger this workflow when `android_flutter/**`,
  `campus_assistant/**` or `.github/workflows/android_flutter.yml` changes. This
  includes `codex/android-core-integration`.
- Pull requests use the same path filters. A manual workflow dispatch is also
  available. The path filters deliberately do not cover unrelated desktop work.
- Every job uses `ubuntu-22.04` with a 30-minute deadline. Direct action references
  are pinned to commit SHAs verified against their upstream GitHub tags.
- Android CI has read-only repository permissions and uploads Actions artifacts;
  it never creates a tag or publishes a GitHub Release.
- The desktop `release.yml` is independent. A push to the integration branch does
  not match its `main`/tag push triggers. Opening a PR to `main` can still trigger
  the existing desktop PR checks.

The toolchain is Flutter **3.24.0 stable**, Java **17**, Android Gradle Plugin
**8.3.0**, Gradle **8.4**, Chaquopy **17.1.0**, and Python **3.11**. Android's
minimum SDK is **26** and compile/target SDK is **34**. CI installs the build
tools and dependencies; an end user does not install Python or Chaquopy on the
phone. The embedded Python runtime is packaged into the APK.

## Required CI gates

1. **Python and Flutter checks.** CI installs the dependencies declared in root
   `pyproject.toml` plus pytest under Python 3.11. It runs the entire root
   `tests/` suite, including Qt UI tests with `QT_QPA_PLATFORM=offscreen`, then
   discovers and runs `android_flutter/tests` using unittest. It stages the
   shared core, resolves Flutter dependencies, runs `flutter analyze`, and runs
   `flutter test`.
2. **Native Android instrumentation.** After those checks pass, separate
   x86_64 emulators run API **26** and **34**. Each job first builds the Flutter
   x64 debug APK to initialize the Flutter Android project and Gradle wrapper,
   then runs `app:connectedDebugAndroidTest`. Native tests under
   `android/app/src/androidTest`, including Kotlin `CoreIntegrationTest`, exercise
   Chaquopy/Python 3.11 and a local MockWebServer. Both matrix entries must pass.
   CI also requires nonempty JUnit reports with executed tests.
3. **Arm64 debug packaging.** Only after both emulators pass does a fresh job
   build `flutter build apk --debug --target-platform android-arm64`. CI verifies
   the debug signature with `apksigner`, checks APK version and arm64 native ABI,
   and computes and rechecks its SHA256 checksum.

The relevant CI commands, shown for maintainers reviewing the workflow, are:

```bash
# Repository root, on the CI runner after dependency setup
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests
python3 -m unittest discover -s android_flutter/tests -v
python3 android_flutter/tools/stage_core.py

# android_flutter/
flutter pub get
flutter analyze
flutter test --reporter expanded
flutter build apk --debug --target-platform android-x64

# android_flutter/android/, with the API 26 or 34 x86_64 emulator running
./gradlew app:connectedDebugAndroidTest -Ptarget-platform=android-x64 --stacktrace

# android_flutter/, only after successful instrumentation on both API levels
flutter build apk --debug --target-platform android-arm64
```

Core staging copies a whitelist of modules into
`android_flutter/android/app/build/generated/python/campus_assistant/`. The
staging location is based on the native app's `projectDir`, even though Flutter
relocates Gradle build outputs to `android_flutter/build/`. This generated copy
is disposable, ignored by git, and must never be edited as the source. Desktop
Qt UI modules and desktop platform integration are not Android runtime
dependencies. Qt is installed only in the CI regression-test environment.

## Artifacts and failure diagnosis

Artifacts are retained for **14 days**:

| Artifact | Contents |
| --- | --- |
| `android-checks` | Python JUnit XML, Python/bridge logs, staging, Flutter analysis and widget-test logs |
| `android-api-26-x86_64-tests` | Emulator application and androidTest APKs, checksum manifest, signature output, instrumentation JUnit/HTML reports, test metadata and logcat |
| `android-api-34-x86_64-tests` | The corresponding API 34 outputs |
| `android-0.5.0+2-arm64-debug` | `czuconnect-0.5.0+2-arm64-debug.apk`, `SHA256SUMS`, `build-info.json`, signature output and APK badging |
| `android-arm64-packaging-reports` | Arm64 build, staging and verification logs |

The arm64 package is the one to install on a compatible physical Android phone.
The x86_64 application and androidTest APKs are emulator test artifacts. The
build metadata records the source commit, CI run, toolchain, versions, ABI,
checksum and prerequisite gates. It explicitly records that arm64 hardware and
the real campus network were not tested by these emulator jobs.

Report/log uploads run even after failed steps. Outputs that were never produced
will be absent; inspect the failing Actions step for dependency setup or emulator
startup failures. A failed test, missing instrumentation report, invalid signature
or checksum failure blocks the final arm64 package. Test commands are not retried
or marked `continue-on-error`, and log pipelines preserve failure exit codes.

To check a downloaded package on a machine that already has SHA256 tools, run
`sha256sum --check SHA256SUMS` from the extracted package directory. The manifest
checks the APK bytes; it does not establish a production signing identity.

## Phone permissions and background limits

Connect to the campus Wi-Fi, configure the account, scene and dorm provider when
applicable, save settings, and explicitly start the guard while the app is open.
Use the status, settings and logs screens to confirm the result. A visible
foreground-service notification is part of background operation; allow
notifications when Android requests permission so that status and the stop action
remain visible.

- **Screen off and background:** the native foreground service, network callbacks
  and alarms support ongoing checks, but Android Doze and manufacturer power
  policies can delay or stop work. Removing the recent-app card is different from
  force-stop; behavior still varies by device.
- **Force-stop:** Android Settings > Force stop stops the service and prevents its
  scheduled work from reviving it. There is no force-stop survival guarantee.
  Reopen the app and explicitly start the guard again. Reboot and OEM task-killer
  behavior also require physical-device verification; do not assume automatic
  recovery.
- **Midnight recovery:** the shared scheduler uses `Asia/Shanghai` and its
  23:58-00:15 recovery window. Android boundary alarms help wake it near the
  window. On Android 12+, exact alarms require the applicable special access.
  If permission is missing or revoked, scheduling falls back to inexact alarms;
  wakeups may be late, especially in Doze. Background foreground-service start
  restrictions also apply. Recovery exactly at midnight is not guaranteed.
- **Battery settings:** use the app's battery-settings entry and review the
  system's unrestricted/battery-optimization settings if reliable background
  checks are needed. OEM autostart/background controls may require separate
  settings. Exemption can improve reliability but is not a survival guarantee
  and can increase battery use.
- **Stopping:** the app/notification stop control must stop checks and cancel
  pending guard work. Reopen and start deliberately when checks are wanted again.

## Manual real-campus acceptance checklist

CI uses offline/local fixtures and emulators. Before calling the Android build
ready for everyday use, record phone model, Android version, app/core version,
permission and battery settings, campus scene, timestamps and observed results.
Do not include account passwords, tokens or unredacted diagnostics in reports.

- Install the arm64 debug APK on actual Android hardware. Check first launch,
  account save/reload, provider selection, status and log screens, notification
  permission, and migration from an earlier test build if applicable.
- On the real public-area and dorm Wi-Fi, test correct credentials and an
  intentionally incorrect account/provider, portal discovery, already-online
  behavior, and recovery after a genuine disconnect. Confirm failures do not
  cause repeated authentication submissions.
- Switch between campus Wi-Fi, another Wi-Fi, no network and mobile data while
  a check is in progress. Confirm stale results do not overwrite the new network's
  status and campus authentication uses the intended Wi-Fi network.
- Leave the phone screen off and the app backgrounded for an extended period;
  test Doze and OEM battery controls. Measure battery impact and confirm logs and
  status remain understandable when checks are delayed.
- Observe a real 23:58-00:15 Beijing-time recovery window with exact-alarm access
  both enabled and denied. Confirm and record the fallback delay; a simulated
  clock or emulator pass is not proof of campus midnight recovery.
- Test stop/start, removing the recent-app card, reboot and a true system
  force-stop separately. Confirm force-stop remains stopped until the user
  reopens and starts the app, and verify the notification stop action cancels work.

The Android package and workflow do not certify Windows or macOS releases.

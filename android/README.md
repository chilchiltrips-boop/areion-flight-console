# Areion Drone Control for Android

A landscape touch transmitter for the Areion FC A1. Opening the app brings up the sticks and the AP connection controls. The screen and all its resources are installed with the APK.

## Connect to the kit

1. Open **Wi-Fi** and join the kit network. Keep the connection if Android reports that this network has no internet.
2. Return to the sticks and tap **Connect AP**.
3. If the controller uses another input, disarm it and choose **Use AP input**. With the sticks neutral and throttle low, tap **Start sender**. The controller reports the channels it receives.

The phone uses the existing Areion Link v2 gateway at `ws://192.168.4.1:8081/areion`. Android binds the connection to the kit Wi-Fi even when mobile data is available. Areion FC A1 AP firmware 3.5.0 supports this protocol.

## Controls

The left thumb controls throttle and yaw. Releasing it holds throttle and centers yaw. The right thumb controls pitch and roll, which center on release. A third finger can tap **STOP** while both pads are held. The screen shows the FC's reported arm state and flight mode. The speed preset changes touch response. Reopening the app after leaving it requires an explicit connection and sender start.

## Install

Requires Android 8.0 or later and a current Android System WebView. The first stable APK installs alongside the preview. Recordings and preferences belong to their respective apps. Subsequent stable APKs install over the existing stable app and keep its data.

| Channel | Package | Download |
| --- | --- | --- |
| Stable | `in.zebjus.areion.console` | Look for `Areion-Drone-Control.apk` in [GitHub Releases](https://github.com/chilchiltrips-boop/areion-flight-console/releases) once the owner publishes the first signed build. |
| Preview | `in.zebjus.areion.console.preview` | [1.1.0 development preview](https://github.com/chilchiltrips-boop/areion-flight-console/releases/download/android-v1.1.0-preview.2/Areion-Flight-Console.apk). Export recordings before uninstalling an older preview if Android reports a signature conflict. |

## Set up Android signing

On the repository owner’s Mac or Linux computer, install Python 3, a JDK with `keytool`, and GitHub CLI. Sign in to an account with permission to manage this repository’s Actions secrets. From the project root, run

```sh
gh auth login --hostname github.com --web
python3 android/scripts/setup-signing.py --publish
```

The script creates a password-protected signing key, saves its backup under `~/.areion/android-signing/`, sets the encrypted repository secret `AREION_ANDROID_SIGNING_BUNDLE`, and starts the Android release workflow on `main`. Keep an encrypted backup of that folder under your control. When moving to another machine, restore the whole folder before running setup again.

For later releases, increase `versionCode` in `android/version.properties`, update `versionName`, and push to `main`. Open **Build Areion Android → Run workflow** and select **Publish a signed Android release after device tests**. Each stable release includes the APK, its checksum, and the public signing certificate. The workflow checks the signer against the previous stable release. [Android release workflow](https://github.com/chilchiltrips-boop/areion-flight-console/actions/workflows/android.yml)

## Build and verify

Use JDK 17, Android SDK 35, Node 22 and Python 3. From the repository root:

```sh
npm ci --ignore-scripts
npm test
android/gradlew -p android :app:assembleDebug :app:assembleDebugAndroidTest
python3 android/scripts/verify-apk.py android/app/build/outputs/apk/debug/app-debug.apk
```

The Android build packages the controller screen and its local dependencies. Device tests exercise multitouch input and exchange Link v2 packets with a loopback test controller.

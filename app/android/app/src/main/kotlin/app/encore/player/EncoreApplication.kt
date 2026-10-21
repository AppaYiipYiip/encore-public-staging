package app.encore.player

import android.app.Application
import android.util.Log

/**
 * The app's [Application], declared in AndroidManifest.xml as `android:name=".EncoreApplication"`.
 *
 * Intentionally minimal: platform-channel registration (audio output, storage, share, power, files)
 * happens in [MainActivity.configureFlutterEngine], where the FlutterEngine is available.
 */
class EncoreApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        Log.d("EncoreApplication", "Application started")
    }
}


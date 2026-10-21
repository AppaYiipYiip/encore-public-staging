package app.encore.player

import android.content.Intent
import android.content.IntentFilter
import android.media.MediaRouter2
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.os.StatFs
import android.provider.OpenableColumns
import android.provider.Settings
import com.ryanheise.audioservice.AudioServiceFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.util.zip.ZipInputStream

/**
 * The only native code of the app besides the media session (`audio_service`)
 * is the few small channels below. Everything else is Dart.
 */
class MainActivity : AudioServiceFragmentActivity() {
    private companion object {
        const val MAX_BYTES = 25 * 1024 * 1024
    }

    private val OUTPUT_CHANNEL = "app.encore/audio_output"
    private val STORAGE_CHANNEL = "app.encore/storage"
    private val SHARE_CHANNEL = "app.encore/share"
    private val POWER_CHANNEL = "app.encore/power"
    private val FILES_CHANNEL = "app.encore/files"
    private val PICK_REQUEST = 7301

    /** The answer owed to Dart while the system file chooser is open. */
    private var pendingPick: MethodChannel.Result? = null

    private var shareChannel: MethodChannel? = null

    /** Text shared to the app that Dart has not picked up yet. */
    private var pendingShared: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pendingShared = sharedTextFrom(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val text = sharedTextFrom(intent) ?: return
        pendingShared = text
        // Dart takes it (and clears it) when it is listening; if it is not
        // yet, `takeShared` finds it at start-up.
        shareChannel?.invokeMethod("shared", text)
    }

    /**
     * "Share > Encore" from Spotify / YouTube Music / a browser, or a link that
     * was tapped in a message (an invitation to a server: `https://.../people/join/...`).
     */
    private fun sharedTextFrom(intent: Intent?): String? {
        if (intent == null) return null
        if (intent.action == Intent.ACTION_VIEW) return intent.dataString
        if (intent.action != Intent.ACTION_SEND || intent.type != "text/plain") return null
        return intent.getStringExtra(Intent.EXTRA_TEXT)
    }

    /**
     * The file the person chose (a list of songs exported from Spotify or
     * Google): its name and text, or, for a .zip such as Spotify's "Download
     * your data", the name and text of the .json / .csv files inside it. Read
     * here, at most [MAX_BYTES] per file, so Dart only ever sees text.
     */
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != PICK_REQUEST) {
            super.onActivityResult(requestCode, resultCode, data)
            return
        }
        val result = pendingPick ?: return
        pendingPick = null
        val uri = if (resultCode == RESULT_OK) data?.data else null
        if (uri == null) {
            result.success(null)
            return
        }
        try {
            var name = "file"
            contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val at = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (at >= 0 && cursor.moveToFirst()) name = cursor.getString(at) ?: name
            }
            val stream = contentResolver.openInputStream(uri)
            if (stream == null) {
                result.error("unreadable", "The file could not be opened.", null)
                return
            }
            val files = stream.use { readFiles(name, it) }
            result.success(files)
        } catch (e: TooBig) {
            result.error("too_big", "That file is too big to be a list of songs.", null)
        } catch (e: Exception) {
            result.error("unreadable", "The file could not be read.", null)
        }
    }

    private class TooBig : Exception()

    private fun readCapped(input: InputStream): ByteArray {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val n = input.read(buffer)
            if (n < 0) break
            out.write(buffer, 0, n)
            if (out.size() > MAX_BYTES) throw TooBig()
        }
        return out.toByteArray()
    }

    private fun readFiles(name: String, input: InputStream): List<Map<String, String>> {
        val bytes = readCapped(input)
        val isZip = bytes.size > 4 && bytes[0] == 'P'.code.toByte() && bytes[1] == 'K'.code.toByte()
        if (!isZip) return listOf(mapOf("name" to name, "text" to String(bytes, Charsets.UTF_8)))
        val found = mutableListOf<Map<String, String>>()
        ZipInputStream(bytes.inputStream()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                val lower = entry.name.lowercase()
                if (entry.isDirectory || !(lower.endsWith(".json") || lower.endsWith(".csv"))) continue
                // Only what holds songs: Spotify's library and playlist files, any CSV.
                val base = lower.substringAfterLast('/')
                if (lower.endsWith(".json") && !(base.startsWith("yourlibrary") || base.startsWith("playlist"))) continue
                found.add(mapOf("name" to entry.name.substringAfterLast('/'),
                                "text" to String(readCapped(zip), Charsets.UTF_8)))
                if (found.size >= 200) break
            }
        }
        return found
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        // A file of songs chosen with the system file chooser (an import).
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, FILES_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method != "pickSongFile") {
                    result.notImplemented()
                } else if (pendingPick != null) {
                    result.error("busy", "A file is already being chosen.", null)
                } else {
                    try {
                        pendingPick = result
                        val open = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                            addCategory(Intent.CATEGORY_OPENABLE)
                            type = "*/*"
                        }
                        startActivityForResult(open, PICK_REQUEST)
                    } catch (e: Exception) {
                        pendingPick = null
                        result.error("unavailable", "There is no file chooser on this phone.", null)
                    }
                }
            }

        // System audio output chooser (speaker / headset / Bluetooth /
        // Audio Sharing). MediaRouter2 shows the platform sheet on API 34+;
        // older versions open the Bluetooth settings page.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, OUTPUT_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method != "showOutputSwitcher") {
                    result.notImplemented()
                } else {
                    try {
                        if (Build.VERSION.SDK_INT >= 34) {
                            result.success(MediaRouter2.getInstance(this).showSystemOutputSwitcher())
                        } else {
                            startActivity(
                                Intent(Settings.ACTION_BLUETOOTH_SETTINGS)
                                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            )
                            result.success(true)
                        }
                    } catch (e: Exception) {
                        result.success(false)
                    }
                }
            }

        // Text handed over by the system Share sheet (an import link).
        shareChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, SHARE_CHANNEL)
        shareChannel!!.setMethodCallHandler { call, result ->
            when (call.method) {
                "takeShared" -> {
                    result.success(pendingShared)
                    pendingShared = null
                }
                // Out: the system share sheet (an invitation link to a friend).
                "send" -> {
                    try {
                        val send = Intent(Intent.ACTION_SEND).apply {
                            type = "text/plain"
                            putExtra(Intent.EXTRA_TEXT, call.arguments as String)
                        }
                        startActivity(Intent.createChooser(send, null))
                        result.success(true)
                    } catch (e: Exception) {
                        result.success(false)
                    }
                }
                else -> result.notImplemented()
            }
        }

        // Battery level / charging / screen state, for the listening log in
        // Diagnostics (real "% per hour of listening" on the owner's phone).
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, POWER_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method != "status") {
                    result.notImplemented()
                } else {
                    try {
                        val battery = registerReceiver(
                            null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
                        val raw = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
                        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
                        val status = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
                        val power = getSystemService(POWER_SERVICE) as PowerManager
                        result.success(
                            mapOf(
                                "level" to (if (raw >= 0 && scale > 0) raw * 100 / scale else -1),
                                "charging" to (status == BatteryManager.BATTERY_STATUS_CHARGING ||
                                    status == BatteryManager.BATTERY_STATUS_FULL),
                                "powerSave" to power.isPowerSaveMode,
                                "screenOn" to power.isInteractive,
                            )
                        )
                    } catch (e: Exception) {
                        result.success(null)
                    }
                }
            }

        // Free space of the volume downloads are written to (the app's
        // files directory), used by the downloads' storage guard.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, STORAGE_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method != "freeBytes") {
                    result.notImplemented()
                } else {
                    try {
                        result.success(StatFs(filesDir.path).availableBytes)
                    } catch (e: Exception) {
                        result.error("storage", e.message, null)
                    }
                }
            }
    }
}

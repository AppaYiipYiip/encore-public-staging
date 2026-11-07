package app.encore.player

import android.content.Intent
import android.content.IntentFilter
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.MediaRouter2
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
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
    private val NETWORK_CHANNEL = "app.encore/network"
    private val FILES_CHANNEL = "app.encore/files"
    private val PICK_REQUEST = 7301

    /** The answer owed to Dart while the system file chooser is open. */
    private var pendingPick: MethodChannel.Result? = null

    private var shareChannel: MethodChannel? = null

    private var outputChannel: MethodChannel? = null
    private var outputCallback: AudioDeviceCallback? = null

    /** Text shared to the app that Dart has not picked up yet. */
    private var pendingShared: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pendingShared = sharedTextFrom(intent)
    }

    override fun onDestroy() {
        outputCallback?.let { (getSystemService(AUDIO_SERVICE) as AudioManager).unregisterAudioDeviceCallback(it) }
        outputCallback = null
        super.onDestroy()
    }

    /**
     * Where the phone's sound goes now: a Bluetooth device, then a wired or USB one, else the phone's own speaker. Android sends media to the
     * most recently connected external output, so the first of these in that order is what the person hears. `name` is what the person sees:
     * a Bluetooth device's own name, "Headphones" for a wired one, "This phone" for the speaker (Dart writes that one itself).
     */
    private fun currentOutput(): Map<String, String> {
        return try {
            val manager = getSystemService(AUDIO_SERVICE) as AudioManager
            val outputs = manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
            // 8 A2DP, 23 hearing aid, 26 BLE headset, 27 BLE speaker, 30 BLE broadcast (the BLE ones are API 31 constants: numbers keep this compiling on API 24).
            val bluetooth = outputs.firstOrNull { it.type in intArrayOf(8, 23, 26, 27, 30) }
            // 3 wired headset, 4 wired headphones, 22 USB headset, 11 USB device, 5 and 6 line out.
            val wired = outputs.firstOrNull { it.type in intArrayOf(3, 4, 22, 11, 5, 6) }
            when {
                bluetooth != null -> mapOf("kind" to "bluetooth", "name" to deviceName(bluetooth))
                wired != null -> mapOf("kind" to "wired", "name" to "Headphones")
                else -> mapOf("kind" to "speaker", "name" to "This phone")
            }
        } catch (e: Exception) {
            mapOf("kind" to "speaker", "name" to "This phone")
        }
    }

    private fun deviceName(device: AudioDeviceInfo): String =
        device.productName?.toString()?.trim().orEmpty().ifEmpty { "Bluetooth" }

    /** Tells Dart whenever an output appears or goes (a headset plugged in, a Bluetooth device switched off). */
    private fun watchOutputDevices() {
        if (outputCallback != null) return
        val manager = getSystemService(AUDIO_SERVICE) as AudioManager
        val callback = object : AudioDeviceCallback() {
            override fun onAudioDevicesAdded(addedDevices: Array<out AudioDeviceInfo>?) = push()
            override fun onAudioDevicesRemoved(removedDevices: Array<out AudioDeviceInfo>?) = push()
            private fun push() {
                runOnUiThread { outputChannel?.invokeMethod("outputChanged", currentOutput()) }
            }
        }
        manager.registerAudioDeviceCallback(callback, null)
        outputCallback = callback
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
        outputChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, OUTPUT_CHANNEL)
        watchOutputDevices()
        outputChannel!!
            .setMethodCallHandler { call, result ->
                if (call.method == "currentOutput") {
                    result.success(currentOutput())
                } else if (call.method != "showOutputSwitcher") {
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

        // Whether Android itself found internet on the active network (NET_CAPABILITY_VALIDATED): false for a mobile network with no data
        // and for a Wi-Fi with a sign-in page, true otherwise. Android does that check; the app makes no call of its own (ADR-R38). `null` when
        // it cannot be known. It only chooses the words of the "server does not answer" strip (D-45, CN-4b).
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, NETWORK_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method != "validated") {
                    result.notImplemented()
                } else {
                    try {
                        val manager = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager
                        val capabilities = manager.getNetworkCapabilities(manager.activeNetwork)
                        result.success(
                            capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED))
                    } catch (e: Exception) {
                        result.success(null)
                    }
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

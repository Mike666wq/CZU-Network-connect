package io.github.Mike666wq.czuconnect

import android.content.Context
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.SystemClock
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicLong

/** A single worker owns configuration, scheduler and Supervisor for this process. */
object GuardRuntime {
    private val thread = HandlerThread("campus-core").apply { start() }
    private val worker = Handler(thread.looper)
    private val main = Handler(Looper.getMainLooper())
    private val generation = AtomicLong(0)
    @Volatile private var bridge: PyObject? = null
    @Volatile var running = false
        private set
    @Volatile private var updatedAt = SystemClock.elapsedRealtime()
    @Volatile var snapshot = JSONObject().put("status", "等待检查").put("message", "")
        .put("online", false).put("coreVersion", "").put("nextSeconds", 0).put("logs", JSONArray()).toString()
        private set

    private fun core(context: Context): PyObject {
        bridge?.let { return it }
        if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
        return Python.getInstance().getModule("campus_android").callAttr("Bridge", context.filesDir.absolutePath)!!
            .also { bridge = it }
    }

    private fun publish(value: PyObject) {
        snapshot = value.callAttr("snapshot").toString()
        updatedAt = SystemClock.elapsedRealtime()
    }

    fun request(context: Context, method: String, payload: String? = null, callback: (Any?, Boolean) -> Unit) {
        worker.post {
            try {
                val value = core(context)
                val answer: Any? = when (method) {
                    "getConfig" -> jsonMap(JSONObject(value.callAttr("get_config").toString()))
                    "saveConfig" -> { value.callAttr("save_config", payload ?: "{}"); null }
                    else -> throw IllegalArgumentException()
                }
                publish(value)
                main.post { callback(answer, false) }
            } catch (_: Exception) { main.post { callback(null, true) } }
        }
    }

    fun begin(context: Context) {
        if (running) return
        running = true
        val token = generation.incrementAndGet()
        worker.post {
            if (generation.get() != token || !running) return@post
            try {
                val value = core(context)
                if (generation.get() == token && running) value.callAttr("resume")
                else value.callAttr("stop")
            } catch (_: Exception) { if (running) fail() }
        }
    }

    fun stop() {
        running = false
        generation.incrementAndGet()
        snapshot = JSONObject(snapshot).put("status", "已停止").put("online", false)
            .put("message", "自动守护已停止").put("nextSeconds", 0).toString()
        // This method only sets cancellation/generation; it never waits on the worker lock.
        try { bridge?.callAttr("stop") } catch (_: Exception) { fail() }
        AndroidHttp.cancelAll()
        worker.post { try { bridge?.let { publish(it) } } catch (_: Exception) { fail() } }
    }

    fun networkChanged(id: String) {
        generation.incrementAndGet()
        try { bridge?.callAttr("network_changed", id) } catch (_: Exception) { fail() }
        AndroidHttp.cancelAll()
        snapshot = JSONObject(snapshot).put("status", "等待检查").put("online", false)
            .put("message", "网络或配置变化，等待重新检查").put("nextSeconds", 0).toString()
    }

    fun noWifi() {
        snapshot = JSONObject(snapshot).put("status", "等待 Wi-Fi")
            .put("message", "请连接校园 Wi-Fi；不会使用蜂窝网络认证")
            .put("online", false).put("nextSeconds", 30).toString()
        updatedAt = SystemClock.elapsedRealtime()
    }

    fun tick(context: Context, networkId: String, force: Boolean, completed: (Int) -> Unit) {
        val token = generation.get()
        worker.post {
            if (!running || token != generation.get()) { main.post { completed(0) }; return@post }
            var delay = 30
            try {
                val value = core(context)
                if (running && token == generation.get()) {
                    value.callAttr("resume")
                    delay = value.callAttr("tick", networkId, force).toInt().coerceAtLeast(1)
                    if (running && token == generation.get()) publish(value)
                }
            } catch (_: Exception) { fail() }
            main.post { completed(if (running && token == generation.get()) delay else 0) }
        }
    }

    private fun fail() {
        snapshot = JSONObject(snapshot).put("status", "检查暂时失败").put("message", "请检查配置后重试")
            .put("online", false).put("nextSeconds", 30).toString()
        updatedAt = SystemClock.elapsedRealtime()
    }

    fun status(): MutableMap<String, Any?> = jsonMap(JSONObject(snapshot)).apply {
        put("running", running)
        val seconds = (get("nextSeconds") as? Number)?.toLong() ?: 0L
        put("nextSeconds", (seconds - (SystemClock.elapsedRealtime() - updatedAt) / 1000L).coerceAtLeast(0L))
    }

    private fun jsonValue(value: Any?): Any? = when (value) {
        JSONObject.NULL -> null
        is JSONObject -> jsonMap(value)
        is JSONArray -> (0 until value.length()).map { jsonValue(value.get(it)) }
        else -> value
    }
    private fun jsonMap(value: JSONObject): MutableMap<String, Any?> =
        value.keys().asSequence().associateWith { jsonValue(value.get(it)) }.toMutableMap()
}

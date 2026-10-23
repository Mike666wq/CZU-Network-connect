package io.github.Mike666wq.czuconnect

import android.net.Network
import android.util.Base64
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Dns
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.Proxy
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.zip.GZIPInputStream

/** One cancellable request: no redirects, proxy inheritance or HTTP logging. */
object AndroidHttp {
    private val active = ConcurrentHashMap.newKeySet<Ticket>()
    @Volatile private var wifi: Network? = null
    private val client = OkHttpClient.Builder()
        .proxy(Proxy.NO_PROXY).followRedirects(false).followSslRedirects(false)
        .retryOnConnectionFailure(false).build()

    @JvmStatic @Synchronized fun setNetwork(network: Network?) {
        if (wifi != network) {
            cancelAll()
            wifi = network
        }
    }

    @JvmStatic @Synchronized fun cancelAll() { active.toList().forEach { it.cancel() } }

    @JvmStatic @Synchronized fun start(url: String, headersJson: String, timeoutMs: Long): Ticket {
        val request = Request.Builder().url(url)
        val host = request.build().url.host
        if (host !in setOf("127.0.0.1", "localhost", "::1") && (wifi == null || !GuardRuntime.running))
            throw IOException("Wi-Fi 不可用或守护已停止")
        val builder = client.newBuilder().callTimeout(timeoutMs, TimeUnit.MILLISECONDS)
            .connectTimeout(timeoutMs, TimeUnit.MILLISECONDS).readTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        wifi?.let { network ->
            builder.socketFactory(network.socketFactory)
            builder.dns(Dns { host -> network.getAllByName(host).toList() })
        }
        val headers = JSONObject(headersJson)
        headers.keys().forEach { key -> request.header(key, headers.getString(key)) }
        if (!headers.has("User-Agent")) request.header("User-Agent", "CampusNetworkAssistant/Android")
        val ticket = Ticket(builder.build().newCall(request.build()), url)
        active.add(ticket)
        ticket.enqueue()
        return ticket
    }

    class Ticket internal constructor(private val call: Call, private val originalUrl: String) {
        private val done = CountDownLatch(1)
        @Volatile private var reply: String? = null
        @Volatile private var error = "网络请求失败"

        internal fun enqueue() {
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) { finish() }
                override fun onResponse(call: Call, response: Response) {
                    try {
                        response.use {
                            val body = response.body
                            val raw = body?.byteStream()
                            val stream = if (response.header("Content-Encoding").equals("gzip", true) && raw != null)
                                GZIPInputStream(raw) else raw
                            val output = ByteArrayOutputStream()
                            if (stream != null) {
                                stream.use {
                                    val buffer = ByteArray(8192)
                                    while (true) {
                                        val size = it.read(buffer)
                                        if (size < 0) break
                                        if (output.size() + size > 1_000_000) {
                                            error = "门户响应过大"
                                            throw IOException(error)
                                        }
                                        output.write(buffer, 0, size)
                                    }
                                }
                            }
                            val responseHeaders = JSONObject()
                            response.headers.names().forEach { name -> responseHeaders.put(name, response.header(name)) }
                            reply = JSONObject().put("status", response.code)
                                .put("body", Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP))
                                .put("encoding", body?.contentType()?.charset()?.name() ?: "utf-8")
                                .put("final", originalUrl).put("headers", responseHeaders).toString()
                        }
                    } catch (_: Exception) {
                        // Never let credential-bearing OkHttp exceptions enter Python or logcat.
                    } finally { finish() }
                }
            })
        }

        private fun finish() { active.remove(this); done.countDown() }
        fun awaitDone(ms: Long): Boolean = done.await(ms, TimeUnit.MILLISECONDS)
        fun cancel() { call.cancel() }
        fun result(): String = reply ?: throw IOException(error)
    }
}

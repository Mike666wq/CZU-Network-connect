package io.github.Mike666wq.czuconnect

import android.content.Context
import android.content.Intent
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okio.Buffer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.zip.GZIPOutputStream

@RunWith(AndroidJUnit4::class)
class CoreIntegrationTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context get() = instrumentation.targetContext

    @Before fun setup() {
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        AndroidHttp.setNetwork(null)
    }

    @After fun cleanup() {
        instrumentation.runOnMainSync { GuardService.disable(context) }
        AndroidHttp.cancelAll()
        AndroidHttp.setNetwork(null)
    }

    @Test fun pythonCoreAuthenticatesThroughNativeLoopbackHttp() {
        val logins = AtomicInteger()
        val probes = AtomicInteger()
        val server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.requestUrl!!.encodedPath
                val response = MockResponse().setHeader("Content-Type", "application/javascript; charset=utf-8")
                return when (path) {
                    "/probe" -> if (probes.incrementAndGet() == 1) response.setResponseCode(503) else response.setResponseCode(204)
                    "/" -> response.setBody("<html>/drcom/<script src='a41.js'></script><script>v4ip='10.20.30.40';</script></html>")
                    "/drcom/chkstatus" -> response.setBody("drfixture({\"result\":0});")
                    "/eportal/portal/page/loadConfig" -> response.setBody("drfixture({\"code\":1,\"data\":{\"program_index\":\"fixture\",\"login_method\":1,\"en_md5\":0,\"password_cut\":0,\"account_prefix\":1,\"enable_r3\":0,\"account_suffix\":\"\",\"io_mode\":0}});")
                    "/eportal/portal/login" -> {
                        assertEquals("fixture-secret", request.requestUrl!!.queryParameter("user_password"))
                        logins.incrementAndGet()
                        response.setBody("drfixture({\"result\":1});")
                    }
                    else -> response.setResponseCode(404)
                }
            }
        }
        server.start()
        try {
            val dir = context.cacheDir.resolve("core-${System.nanoTime()}").apply { mkdirs() }
            val version = Python.getInstance().getModule("device_checks")
                .callAttr("integration", dir.absolutePath, server.url("/").toString()).toString()
            assertEquals(Python.getInstance().getModule("campus_assistant")["__version__"].toString(), version)
            assertEquals(1, logins.get())
            assertEquals(2, probes.get())
        } finally { server.shutdown() }
    }

    @Test fun requestsHaveTotalDeadlineCancellationAndBodyBounds() {
        val server = MockWebServer()
        val compressed = ByteArrayOutputStream()
        GZIPOutputStream(compressed).use { it.write(ByteArray(1_000_001)) }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when (request.requestUrl!!.encodedPath) {
                "/slow", "/cancel" -> MockResponse().setBody("slow").setBodyDelay(3, TimeUnit.SECONDS)
                "/large" -> MockResponse().setHeader("Content-Encoding", "gzip")
                    .setBody(Buffer().write(compressed.toByteArray()))
                "/raw-gzip" -> MockResponse().setBody(Buffer().write(compressed.toByteArray()))
                "/redirect" -> MockResponse().setResponseCode(302).setHeader("Location", "http://untrusted.invalid/")
                else -> MockResponse().setResponseCode(404)
            }
        }
        server.start()
        try {
            val slow = AndroidHttp.start(server.url("/slow?password=fixture-secret").toString(), "{}", 150)
            assertTrue(slow.awaitDone(2000))
            try { slow.result(); fail("deadline must reject result") } catch (expected: java.io.IOException) {
                assertFalse(expected.message.orEmpty().contains("fixture-secret"))
            }
            val cancelled = AndroidHttp.start(server.url("/cancel").toString(), "{}", 5000)
            cancelled.cancel()
            assertTrue(cancelled.awaitDone(2000))
            try { cancelled.result(); fail("cancel must reject result") } catch (_: java.io.IOException) { }
            val large = AndroidHttp.start(server.url("/large").toString(), "{}", 3000)
            assertTrue(large.awaitDone(4000))
            try { large.result(); fail("oversized inflated body accepted") } catch (_: java.io.IOException) { }
            val rawGzip = AndroidHttp.start(server.url("/raw-gzip").toString(), "{}", 3000)
            assertTrue(rawGzip.awaitDone(4000))
            try { rawGzip.result(); fail("oversized headerless gzip accepted") } catch (_: java.io.IOException) { }
            val redirect = AndroidHttp.start(server.url("/redirect").toString(), "{}", 1000)
            assertTrue(redirect.awaitDone(2000))
            assertEquals(302, JSONObject(redirect.result()).getInt("status"))
        } finally { server.shutdown() }
    }

    @Test fun guardSurvivesActivityCloseAndStopIsFinal() {
        val fixture = context.cacheDir.resolve("lifecycle-${System.nanoTime()}").apply { mkdirs() }
        val bridge = Python.getInstance().getModule("device_checks").callAttr("safe_bridge", fixture.absolutePath)
        val field = GuardRuntime::class.java.getDeclaredField("bridge").apply { isAccessible = true }
        field.set(null, bridge)
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        instrumentation.runOnMainSync {
            repeat(3) { context.startForegroundService(Intent(context, GuardService::class.java).setAction(GuardService.START)) }
        }
        await { GuardRuntime.running }
        scenario.close()
        assertTrue(GuardRuntime.running)
        assertTrue(GuardService.wanted(context))
        instrumentation.runOnMainSync { GuardService.disable(context) }
        await { !GuardRuntime.running }
        assertFalse(GuardService.wanted(context))
        assertFalse(GuardRuntime.status()["running"] as Boolean)
    }

    @Test fun recoveryAlarmsWorkWithCurrentPermissionAndCanBeCancelled() {
        GuardAlarms.schedule(context, 60)
        GuardAlarms.cancel(context)
        if (android.os.Build.VERSION.SDK_INT < 31) assertTrue(GuardAlarms.exactAllowed(context))
    }

    @Test fun noWifiNeverFallsBackToCellular() {
        AndroidHttp.setNetwork(null)
        try {
            AndroidHttp.start("http://portal.invalid/?user_password=fixture-secret", "{}", 1000)
            fail("A campus request without Wi-Fi must be rejected before opening a socket")
        } catch (expected: java.io.IOException) {
            assertFalse(expected.message.orEmpty().contains("fixture-secret"))
        }
    }

    private fun await(predicate: () -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
        while (!predicate() && System.nanoTime() < deadline) Thread.sleep(50)
        assertTrue("condition not reached before deadline", predicate())
    }
}

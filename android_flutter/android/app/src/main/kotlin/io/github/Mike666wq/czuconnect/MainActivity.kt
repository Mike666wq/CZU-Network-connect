package io.github.Mike666wq.czuconnect

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity: FlutterActivity() {
    private val CHANNEL = "io.github.Mike666wq.czuconnect/guard"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "getStatus" -> {
                    result.success(mapOf(
                        "status" to "未连接",
                        "running" to false
                    ))
                }
                "connectNow" -> {
                    val username = call.argument<String>("username") ?: ""
                    result.success("连接请求已收到: $username")
                }
                "startGuard" -> {
                    result.success(null)
                }
                "stopGuard" -> {
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }
}

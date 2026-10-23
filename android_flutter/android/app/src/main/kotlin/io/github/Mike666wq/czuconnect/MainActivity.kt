package io.github.Mike666wq.czuconnect

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "io.github.Mike666wq.czuconnect/guard")
            .setMethodCallHandler { call, result ->
                try {
                    when (call.method) {
                        "getStatus" -> result.success(GuardRuntime.status().apply {
                            put("exactAlarmAllowed", GuardAlarms.exactAllowed(this@MainActivity))
                            put("batteryExempt", (getSystemService(POWER_SERVICE) as PowerManager)
                                .isIgnoringBatteryOptimizations(packageName))
                        })
                        "getConfig", "saveConfig" -> {
                            val payload = if (call.method == "saveConfig") JSONObject(call.arguments as Map<*, *>).toString() else null
                            if (call.method == "saveConfig") GuardRuntime.networkChanged("config-change")
                            GuardRuntime.request(applicationContext, call.method, payload) { value, failed ->
                                if (failed) result.error("CORE_ERROR", "配置操作失败，请检查填写内容", null)
                                else {
                                    result.success(value)
                                    if (call.method == "saveConfig" && GuardRuntime.running) {
                                        try { startService(GuardService.CHECK) } catch (_: Exception) { /* Existing timer remains active. */ }
                                    }
                                }
                            }
                        }
                        "connectNow", "startGuard" -> { startService(GuardService.START); result.success(null) }
                        "stopGuard" -> { GuardService.disable(this); result.success(null) }
                        "requestNotifications" -> {
                            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 11)
                            result.success(null)
                        }
                        "openBatterySettings" -> {
                            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)); result.success(null)
                        }
                        "openAlarmSettings" -> {
                            if (Build.VERSION.SDK_INT >= 31) startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                                Uri.parse("package:$packageName")))
                            result.success(null)
                        }
                        else -> result.notImplemented()
                    }
                } catch (_: Exception) { result.error("ANDROID_ERROR", "操作暂时失败，请重试", null) }
            }
    }

    private fun startService(action: String) {
        startForegroundService(Intent(this, GuardService::class.java).setAction(action))
    }
}

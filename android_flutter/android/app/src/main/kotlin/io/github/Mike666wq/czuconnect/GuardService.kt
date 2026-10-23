package io.github.Mike666wq.czuconnect

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager

class GuardService : Service() {
    companion object {
        const val START = "campus.START"
        const val CHECK = "campus.CHECK"
        const val BOUNDARY = "campus.BOUNDARY"
        const val STOP = "campus.STOP"
        private const val CHANNEL = "campus-guard"
        private const val NOTICE = 1001
        fun wanted(context: Context): Boolean = context.getSharedPreferences("guard", MODE_PRIVATE)
            .getBoolean("enabled", false)
        fun disable(context: Context) {
            context.getSharedPreferences("guard", MODE_PRIVATE).edit().putBoolean("enabled", false).apply()
            GuardRuntime.stop()
            GuardAlarms.cancel(context)
            context.stopService(Intent(context, GuardService::class.java))
        }
    }

    private val main = Handler(Looper.getMainLooper())
    private lateinit var connectivity: ConnectivityManager
    private var network: Network? = null
    private var checking = false
    private var pending = false
    private var pendingForce = false
    private var alive = false
    private var wake: PowerManager.WakeLock? = null
    private val scheduled = Runnable { check(false) }
    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(value: Network) { main.post { selectNetwork() } }
        override fun onLost(value: Network) { main.post { selectNetwork() } }
        override fun onLinkPropertiesChanged(value: Network, properties: android.net.LinkProperties) {
            main.post { selectNetwork() }
        }
    }
    private var networkId = "none"

    override fun onCreate() {
        super.onCreate()
        alive = true
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "校园网守护", NotificationManager.IMPORTANCE_LOW))
        if (Build.VERSION.SDK_INT >= 34) startForeground(NOTICE, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(NOTICE, notification())
        connectivity = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager
        selectNetwork(false)
        connectivity.registerNetworkCallback(NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), callback)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) { disable(this); return START_NOT_STICKY }
        if (intent == null || intent.action == CHECK || intent.action == BOUNDARY) {
            if (!wanted(this)) { stopSelf(); return START_NOT_STICKY }
        }
        getSharedPreferences("guard", MODE_PRIVATE).edit().putBoolean("enabled", true).apply()
        GuardRuntime.begin(this)
        check(intent?.action == START)
        return START_STICKY
    }

    private fun selectNetwork(trigger: Boolean = true) {
        val wifi = connectivity.allNetworks.firstOrNull {
            connectivity.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
        }
        val id = if (wifi == null) "none" else wifi.toString() + ":" +
            (connectivity.getLinkProperties(wifi)?.toString()?.hashCode() ?: 0)
        if (id != networkId) changed(wifi, id, trigger)
    }

    private fun changed(value: Network?, id: String, trigger: Boolean = true) {
        if (id == networkId) return
        network = value
        networkId = id
        GuardRuntime.networkChanged(id)
        AndroidHttp.setNetwork(value)
        if (trigger && GuardRuntime.running) check(false)
    }

    private fun check(force: Boolean) {
        if (!alive || !GuardRuntime.running) return
        main.removeCallbacks(scheduled)
        if (checking) { pending = true; pendingForce = pendingForce || force; return }
        if (network == null) {
            GuardRuntime.noWifi()
            GuardAlarms.schedule(this, 30)
            main.postDelayed(scheduled, 30_000)
            return
        }
        checking = true
        wake = (getSystemService(POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "$packageName:check").apply { acquire(120_000) }
        GuardRuntime.tick(this, networkId, force) { delay ->
            if (wake?.isHeld == true) wake?.release()
            wake = null
            checking = false
            if (!alive || !GuardRuntime.running) return@tick
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(NOTICE, notification())
            if (pending) {
                val forced = pendingForce; pending = false; pendingForce = false
                check(forced)
            } else {
                val next = if (delay == 0) 1 else delay
                GuardAlarms.schedule(this, next)
                main.postDelayed(scheduled, next * 1000L)
            }
        }
    }

    private fun notification(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, GuardService::class.java).setAction(STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_guard)
            .setContentTitle("校园网守护中").setContentText(GuardRuntime.status()["status"]?.toString() ?: "等待检查")
            .setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null, "停止守护", stop).build()).build()
    }

    override fun onDestroy() {
        alive = false
        main.removeCallbacksAndMessages(null)
        connectivity.unregisterNetworkCallback(callback)
        GuardRuntime.stop()
        AndroidHttp.setNetwork(null)
        if (wake?.isHeld == true) wake?.release()
        if (!wanted(this)) GuardAlarms.cancel(this)
        super.onDestroy()
    }
    override fun onBind(intent: Intent?): IBinder? = null
}

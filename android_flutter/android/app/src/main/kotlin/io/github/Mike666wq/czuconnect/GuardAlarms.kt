package io.github.Mike666wq.czuconnect

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import java.util.Calendar
import java.util.TimeZone

object GuardAlarms {
    private fun alarm(context: Context, id: Int): PendingIntent = PendingIntent.getBroadcast(
        context, id, Intent(context, GuardAlarmReceiver::class.java).putExtra("boundary", id != 0),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    fun exactAllowed(context: Context): Boolean = Build.VERSION.SDK_INT < 31 ||
        (context.getSystemService(Context.ALARM_SERVICE) as AlarmManager).canScheduleExactAlarms()

    fun schedule(context: Context, delaySeconds: Int) {
        val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        // Heartbeat alarms are intentionally inexact; exact permission is only used at recovery boundaries.
        manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,
            System.currentTimeMillis() + delaySeconds.coerceAtLeast(1) * 1000L, alarm(context, 0))
        listOf(23 to 58, 0 to 0, 0 to 8).forEachIndexed { index, (hour, minute) ->
            val moment = Calendar.getInstance(TimeZone.getTimeZone("Asia/Shanghai")).apply {
                set(Calendar.HOUR_OF_DAY, hour); set(Calendar.MINUTE, minute)
                set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
                if (timeInMillis <= System.currentTimeMillis()) add(Calendar.DAY_OF_YEAR, 1)
            }.timeInMillis
            try {
                if (exactAllowed(context)) manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,
                    moment, alarm(context, index + 1))
                else manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, moment, alarm(context, index + 1))
            } catch (_: SecurityException) {
                manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, moment, alarm(context, index + 1))
            }
        }
    }

    fun cancel(context: Context) {
        val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        (0..3).forEach { manager.cancel(alarm(context, it)) }
    }
}

class GuardAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (!GuardService.wanted(context)) return
        try {
            context.startForegroundService(Intent(context, GuardService::class.java)
                .setAction(if (intent.getBooleanExtra("boundary", false)) GuardService.BOUNDARY else GuardService.CHECK))
        } catch (_: IllegalStateException) {
            // An inexact alarm may be deferred/restricted by the OS. Keep the UI resume path available.
        }
    }
}

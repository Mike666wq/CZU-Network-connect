import 'dart:async';

import 'package:czuconnect/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('io.github.Mike666wq.czuconnect/guard');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  late Map<String, Object?> config;
  late Map<String, Object?> status;
  late List<MethodCall> calls;
  FutureOr<Object?> Function(MethodCall)? override;

  Map<String, Object?> emptyConfig() => {
        'username': '',
        'password': '',
        'isp': '-1',
        'scene': 'auto',
      };

  Finder keyed(String key) => find.byKey(ValueKey(key));

  DropdownButton<String> dropdown(WidgetTester tester, String key) {
    return tester.widget<DropdownButton<String>>(
      find.descendant(
        of: keyed(key),
        matching: find.byType(DropdownButton<String>),
      ),
    );
  }

  Future<void> launch(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1000, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(() async {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });
    await tester.pumpWidget(const CzuConnectApp());
    await tester.pumpAndSettle();
  }

  Future<void> tapKey(WidgetTester tester, String key) async {
    await tester.ensureVisible(keyed(key));
    await tester.tap(keyed(key));
    await tester.pumpAndSettle();
  }

  Future<void> settings(WidgetTester tester) async {
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
  }

  List<MethodCall> methodCalls(String method) =>
      calls.where((call) => call.method == method).toList();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    config = emptyConfig();
    status = {
      'status': '等待检查',
      'message': '尚未完成网络检查',
      'running': false,
      'online': false,
      'coreVersion': '0.5.0-test',
      'nextSeconds': null,
      'logs': <String>[],
      'exactAlarmAllowed': false,
      'batteryExempt': false,
    };
    calls = [];
    override = null;
    TestWidgetsFlutterBinding.instance
        .handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      final handler = override;
      if (handler != null) return await handler(call);
      switch (call.method) {
        case 'getConfig':
          expect(call.arguments, isNull);
          return config;
        case 'saveConfig':
          config = Map<String, Object?>.from(call.arguments as Map);
          return null;
        case 'getStatus':
          expect(call.arguments, isNull);
          return status;
        case 'connectNow':
        case 'startGuard':
        case 'stopGuard':
        case 'openBatterySettings':
        case 'openAlarmSettings':
        case 'requestNotifications':
          expect(call.arguments, isNull);
          return null;
        default:
          throw MissingPluginException();
      }
    });
  });

  tearDown(() {
    messenger.setMockMethodCallHandler(channel, null);
  });

  testWidgets('fresh install keeps provider unselected and blue dark theme',
      (tester) async {
    await launch(tester);
    expect(methodCalls('saveConfig'), isEmpty);
    expect(find.text('核心版本：0.5.0-test'), findsOneWidget);
    expect(find.text('尚未完成网络检查'), findsOneWidget);
    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.theme!.brightness, Brightness.dark);
    expect(
      app.theme!.colorScheme,
      ColorScheme.fromSeed(
        seedColor: const Color(0xFF2196F3),
        brightness: Brightness.dark,
      ),
    );
    await settings(tester);
    final provider = tester.widget<DropdownButtonFormField<String>>(
      keyed('isp--1'),
    );
    expect(provider.initialValue, '-1');
    expect(dropdown(tester, 'isp--1').items!.map((item) => item.value),
        ['-1', '', '@cmcc', '@unicom', '@telecom']);
    final scene = tester.widget<DropdownButtonFormField<String>>(
      keyed('scene-auto'),
    );
    expect(scene.initialValue, 'auto');
    expect(dropdown(tester, 'scene-auto').items!.map((item) => item.value),
        ['auto', 'public', 'dorm']);
    await tapKey(tester, 'save');
    expect(methodCalls('saveConfig').single.arguments, emptyConfig());
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getKeys(), isEmpty);
  });

  testWidgets('unrelated preferences do not create a legacy Mobile selection',
      (tester) async {
    SharedPreferences.setMockInitialValues({'unrelated': 'keep-me'});
    await launch(tester);
    expect(methodCalls('saveConfig'), isEmpty);
    await settings(tester);
    expect(keyed('isp--1'), findsOneWidget);
  });

  for (final provider in ['-1', '', '@cmcc', '@unicom', '@telecom']) {
    testWidgets('native config round trips provider "$provider" and password',
        (tester) async {
      config = {
        'username': 'native-account',
        'password': '  native password\n',
        'isp': provider,
        'scene': 'dorm',
      };
      final expected = Map<String, Object?>.from(config);
      SharedPreferences.setMockInitialValues({
        'username': 'stale-legacy-account',
        'password': 'stale-legacy-password',
        'isp': 'cmcc',
      });
      await launch(tester);
      expect(methodCalls('saveConfig'), isEmpty);
      await settings(tester);
      expect(tester.widget<TextField>(keyed('username')).controller!.text,
          'native-account');
      final password = tester.widget<TextField>(keyed('password'));
      expect(password.controller!.text, '  native password\n');
      expect(password.obscureText, isTrue);
      expect(keyed('isp-$provider'), findsOneWidget);
      expect(keyed('scene-dorm'), findsOneWidget);
      await tapKey(tester, 'save');
      expect(methodCalls('saveConfig').single.arguments, expected);
    });
  }

  for (final provider in <String?, String>{
    null: '@cmcc',
    'cmcc': '@cmcc',
    'unicom': '@unicom',
    'telecom': '@telecom',
    '': '',
    '-1': '-1',
    'invalid': '-1',
  }.entries) {
    testWidgets('migrates persisted legacy provider ${provider.key} once',
        (tester) async {
      SharedPreferences.setMockInitialValues({
        'username': 'legacy-account',
        'password': '  legacy password  ',
        if (provider.key != null) 'isp': provider.key!,
        'unrelated': 'keep-me',
      });
      await launch(tester);
      expect(methodCalls('saveConfig').single.arguments, {
        'username': 'legacy-account',
        'password': '  legacy password  ',
        'isp': provider.value,
        'scene': 'auto',
      });
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('username'), isNull);
      expect(prefs.getString('password'), isNull);
      expect(prefs.getString('isp'), isNull);
      expect(prefs.getString('unrelated'), 'keep-me');
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpWidget(const CzuConnectApp());
      await tester.pumpAndSettle();
      expect(methodCalls('saveConfig'), hasLength(1));
      await settings(tester);
      expect(tester.widget<TextField>(keyed('password')).controller!.text,
          '  legacy password  ');
    });
  }

  testWidgets('failed migration preserves legacy credentials and supports retry',
      (tester) async {
    SharedPreferences.setMockInitialValues({
      'username': 'legacy-account',
      'password': 'legacy-password',
      'isp': 'telecom',
    });
    override = (call) {
      if (call.method == 'getConfig') return config;
      if (call.method == 'getStatus') return status;
      throw PlatformException(
        code: 'failed',
        message: 'legacy-account legacy-password',
      );
    };
    await launch(tester);
    expect(find.text('配置读取失败，请重试'), findsOneWidget);
    expect(tester.widget<ButtonStyleButton>(keyed('connect')).onPressed, isNull);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('password'), 'legacy-password');
    override = null;
    await settings(tester);
    await tapKey(tester, 'reloadConfig');
    expect(config['isp'], '@telecom');
    expect(config['password'], 'legacy-password');
    expect(prefs.getString('password'), isNull);
    expect(tester.widget<TextField>(keyed('password')).controller!.text,
        'legacy-password');
    expect(tester.takeException(), isNull);
  });

  testWidgets('provider and scene edits save native values without trimming password',
      (tester) async {
    await launch(tester);
    await settings(tester);
    await tester.enterText(keyed('username'), '  student-account  ');
    await tester.enterText(keyed('password'), '  exact password  ');
    await tester.tap(keyed('isp--1'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('中国联通').last);
    await tester.pumpAndSettle();
    await tester.tap(keyed('scene-auto'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('公共网').last);
    await tester.pumpAndSettle();
    await tapKey(tester, 'save');
    expect(methodCalls('saveConfig').single.arguments, {
      'username': 'student-account',
      'password': '  exact password  ',
      'isp': '@unicom',
      'scene': 'public',
    });
    expect((await SharedPreferences.getInstance()).getKeys(), isEmpty);
  });

  testWidgets('connect saves first and accepts null queued response',
      (tester) async {
    config = {
      'username': 'student-account',
      'password': 'saved-password',
      'isp': '',
      'scene': 'public',
    };
    await launch(tester);
    calls.clear();
    await tapKey(tester, 'connect');
    expect(calls.map((call) => call.method),
        ['saveConfig', 'connectNow', 'getStatus']);
    expect(methodCalls('connectNow').single.arguments, isNull);
    expect(find.text('立即连接并守护'), findsOneWidget);
    expect(find.text('连接及守护请求已发送，检查已排队'), findsOneWidget);
    expect(find.text('网络离线'), findsOneWidget);
    expect(find.text('未守护'), findsOneWidget);
  });

  testWidgets('connect also shows guarding when confirmed by native status',
      (tester) async {
    await launch(tester);
    override = (call) {
      if (call.method == 'connectNow') status['running'] = true;
      if (call.method == 'getStatus') return status;
      return null;
    };
    await tapKey(tester, 'connect');
    expect(find.text('守护中'), findsOneWidget);
    expect(find.text('停止守护'), findsOneWidget);
    expect(find.text('网络离线'), findsOneWidget);
  });

  testWidgets('guard and connectivity follow independent native fields',
      (tester) async {
    status['running'] = true;
    status['online'] = false;
    status['nextSeconds'] = 37;
    await launch(tester);
    expect(find.text('守护中'), findsOneWidget);
    expect(find.text('网络离线'), findsOneWidget);
    expect(find.text('下次检查：37 秒'), findsOneWidget);
    expect(find.byIcon(Icons.wifi_off), findsOneWidget);
    calls.clear();
    status['running'] = false;
    status['online'] = true;
    await tapKey(tester, 'guard');
    expect(calls.map((call) => call.method), ['stopGuard', 'getStatus']);
    expect(find.text('未守护'), findsOneWidget);
    expect(find.text('网络在线'), findsOneWidget);
    expect(find.text('下次检查：37 秒'), findsNothing);
    calls.clear();
    await tapKey(tester, 'guard');
    expect(calls.map((call) => call.method),
        ['saveConfig', 'startGuard', 'getStatus']);
    // A queued start does not invent a running state before native confirms it.
    expect(find.text('未守护'), findsOneWidget);
  });

  for (final entry in {
    'waiting': '等待检查',
    'paused': '自动检查已暂停',
    'stopped': '检查已停止',
    'checking': '正在检查网络',
    'online': '互联网已连通',
    'authenticated': '校园网已认证',
    'portal': '检测到校园认证门户',
    'needs_config': '需要检查配置',
    'auth_blocked': '认证被拒绝，等待重试',
    'error': '暂时无法检查网络',
    'future_unknown_state': '状态待更新',
  }.entries) {
    testWidgets('localizes native status ${entry.key}', (tester) async {
      status['status'] = entry.key;
      status['message'] = '';
      await launch(tester);
      expect(find.text(entry.value), findsOneWidget);
      expect(find.text(entry.key), findsNothing);
    });
  }

  testWidgets('localizes known native messages and accepts localized messages',
      (tester) async {
    status['status'] = 'checking';
    status['message'] = 'Waiting for a network check';
    await launch(tester);
    expect(find.text('等待网络检查'), findsOneWidget);
    expect(find.text('Waiting for a network check'), findsNothing);
    status['message'] = '请检查当前 Wi-Fi';
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(find.text('请检查当前 Wi-Fi'), findsOneWidget);
  });

  testWidgets('polls every two seconds and immediately on resume, stops on dispose',
      (tester) async {
    await launch(tester);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    calls.clear();
    await tester.pump(const Duration(milliseconds: 1900));
    expect(methodCalls('getStatus'), isEmpty);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump();
    expect(methodCalls('getStatus'), hasLength(1));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(seconds: 6));
    expect(methodCalls('getStatus'), hasLength(1));
    status['online'] = true;
    status['batteryExempt'] = true;
    status['exactAlarmAllowed'] = true;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(methodCalls('getStatus'), hasLength(2));
    expect(find.text('网络在线'), findsOneWidget);
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(methodCalls('getStatus'), hasLength(3));
    await settings(tester);
    expect(find.text('电池优化：已豁免'), findsOneWidget);
    expect(find.text('精确闹钟：已允许'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    calls.clear();
    await tester.pump(const Duration(seconds: 6));
    expect(calls, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('does not overlap slow status requests', (tester) async {
    await launch(tester);
    calls.clear();
    final pending = Completer<Object?>();
    override = (call) => pending.future;
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 8));
    expect(methodCalls('getStatus'), hasLength(1));
    pending.complete(status);
    await tester.pump();
    override = null;
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(methodCalls('getStatus'), hasLength(2));
  });

  testWidgets('serializes rapid actions and disables settings during save',
      (tester) async {
    await launch(tester);
    final pending = Completer<Object?>();
    override = (call) {
      if (call.method == 'saveConfig') return pending.future;
      if (call.method == 'getStatus') return status;
      return null;
    };
    calls.clear();
    final connect = tester.widget<ButtonStyleButton>(keyed('connect')).onPressed!;
    final guard = tester.widget<ButtonStyleButton>(keyed('guard')).onPressed!;
    connect();
    connect();
    guard();
    await tester.pump();
    expect(calls.map((call) => call.method), ['saveConfig']);
    expect(tester.widget<ButtonStyleButton>(keyed('connect')).onPressed, isNull);
    expect(tester.widget<ButtonStyleButton>(keyed('guard')).onPressed, isNull);
    await settings(tester);
    expect(tester.widget<ButtonStyleButton>(keyed('save')).onPressed, isNull);
    expect(tester.widget<TextField>(keyed('password')).enabled, isFalse);
    expect(tester.widget<ButtonStyleButton>(keyed('batterySettings')).onPressed,
        isNull);
    await tester.pump(const Duration(seconds: 4));
    expect(methodCalls('getStatus'), isEmpty);
    pending.complete(null);
    await tester.pumpAndSettle();
    expect(calls.map((call) => call.method),
        ['saveConfig', 'connectNow', 'getStatus']);
    expect(tester.widget<ButtonStyleButton>(keyed('save')).onPressed, isNotNull);
  });

  for (final permission in {
    'batterySettings': 'openBatterySettings',
    'alarmSettings': 'openAlarmSettings',
    'notifications': 'requestNotifications',
  }.entries) {
    testWidgets('delegates ${permission.value} to native', (tester) async {
      await launch(tester);
      await settings(tester);
      calls.clear();
      await tapKey(tester, permission.key);
      expect(calls.map((call) => call.method),
          [permission.value, 'getStatus']);
      expect(calls.first.arguments, isNull);
      expect(methodCalls('saveConfig'), isEmpty);
    });
  }

  testWidgets('native log snapshots replace prior logs and redact credentials',
      (tester) async {
    config = {
      'username': 'private-account',
      'password': 'private-password',
      'isp': '@cmcc',
      'scene': 'auto',
    };
    status['message'] = 'check private-account private-password';
    status['logs'] = ['private-account: private-password', 'safe log'];
    await launch(tester);
    expect(find.text('check [已隐藏] [已隐藏]'), findsOneWidget);
    await tester.tap(find.text('日志'));
    await tester.pumpAndSettle();
    expect(find.text('[已隐藏]: [已隐藏]'), findsOneWidget);
    expect(find.text('safe log'), findsOneWidget);
    expect(find.textContaining('private-account'), findsNothing);
    expect(find.textContaining('private-password'), findsNothing);
    status['logs'] = ['replacement log'];
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(find.text('replacement log'), findsOneWidget);
    expect(find.text('safe log'), findsNothing);
    status['logs'] = <String>[];
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(find.text('暂无日志'), findsOneWidget);
  });

  for (final failingMethod in ['saveConfig', 'connectNow', 'startGuard']) {
    testWidgets('$failingMethod failure is generic and releases busy state',
        (tester) async {
      await launch(tester);
      override = (call) {
        if (call.method == failingMethod) {
          throw PlatformException(
            code: 'secret-code',
            message: 'unknown-account unknown-password',
            details: {'password': 'unknown-password'},
          );
        }
        if (call.method == 'getStatus') return status;
        return null;
      };
      calls.clear();
      await tapKey(tester, failingMethod == 'startGuard' ? 'guard' : 'connect');
      expect(find.text('操作失败，请重试'), findsOneWidget);
      expect(find.textContaining('unknown-password'), findsNothing);
      expect(find.textContaining('secret-code'), findsNothing);
      expect(tester.widget<ButtonStyleButton>(keyed('connect')).onPressed,
          isNotNull);
      if (failingMethod == 'saveConfig') {
        expect(methodCalls('connectNow'), isEmpty);
      }
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('status failures are generic and polling recovers', (tester) async {
    await launch(tester);
    override = (call) {
      throw PlatformException(code: 'private-code', message: 'private-password');
    };
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(find.text('状态查询失败，请重试'), findsOneWidget);
    expect(find.textContaining('private-password'), findsNothing);
    override = null;
    status['online'] = true;
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(find.text('状态查询失败，请重试'), findsNothing);
    expect(find.text('网络在线'), findsOneWidget);
  });

  testWidgets('config failure does not fall back to or overwrite native storage',
      (tester) async {
    SharedPreferences.setMockInitialValues({'password': 'legacy-secret'});
    override = (call) {
      if (call.method == 'getStatus') return status;
      throw MissingPluginException('private native error');
    };
    await launch(tester);
    expect(find.text('配置读取失败，请重试'), findsOneWidget);
    expect(methodCalls('saveConfig'), isEmpty);
    expect(tester.widget<ButtonStyleButton>(keyed('connect')).onPressed, isNull);
    expect(tester.widget<ButtonStyleButton>(keyed('guard')).onPressed, isNull);
    expect((await SharedPreferences.getInstance()).getString('password'),
        'legacy-secret');
    expect(tester.takeException(), isNull);
  });

  for (final pendingMethod in ['getConfig', 'getStatus', 'saveConfig']) {
    testWidgets('safe disposal with $pendingMethod in flight', (tester) async {
      final pending = Completer<Object?>();
      if (pendingMethod == 'saveConfig') await launch(tester);
      override = (call) {
        if (call.method == pendingMethod) return pending.future;
        if (call.method == 'getConfig') return config;
        if (call.method == 'getStatus') return status;
        return null;
      };
      if (pendingMethod == 'saveConfig') {
        await tester.tap(keyed('connect'));
        await tester.pump();
      } else {
        await launch(tester);
      }
      await tester.pumpWidget(const SizedBox.shrink());
      calls.clear();
      pending.complete(pendingMethod == 'getConfig'
          ? config
          : pendingMethod == 'getStatus'
              ? status
              : null);
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      expect(calls, isEmpty);
      expect(tester.takeException(), isNull);
    });
  }
}
